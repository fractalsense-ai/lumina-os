"""
dsa-orchestrator.py — Project Lumina D.S.A. Orchestrator Reference Implementation

Version: 0.1.0
Conforms to: specs/dsa-framework-v1.md
             standards/causal-trace-ledger-v1.md

Implements the Action layer of the D.S.A. framework, connecting:
    Domain Physics → ZPD Monitor → CTL → Prompt Contract

The orchestrator:
  1. Loads Domain Physics (JSON) defining invariants and standing orders.
  2. Holds the current LearningState (initialised from student profile).
  3. For every session turn:
       a. Evaluates the 5 non-ZPD invariants against structured evidence.
       b. Steps the ZPD Monitor to obtain the updated state and a drift decision.
       c. Resolves the final action (invariant failures trump ZPD drift).
       d. Builds a prompt_contract JSON object conforming to the domain schema.
       e. Appends a hash-chained TraceEvent (and, when needed, an
          EscalationRecord) to the Causal Trace Ledger (CTL).
  4. Opens the session with a CommitmentRecord in the CTL.

Design constraints:
  - Standard library only (no external dependencies).
  - ZPD monitor is imported via importlib.util because its filename contains
    hyphens that make it an invalid Python module identifier.
  - All CTL records are hash-chained with SHA-256 canonical JSON, exactly as
    implemented in ctl-commitment-validator.py.

Usage:
    from dsa_orchestrator import DSAOrchestrator, load_domain_physics, load_student_profile_yaml
    domain = load_domain_physics("domain-packs/education/algebra-level-1/domain-physics.json")
    profile = load_student_profile_yaml("domain-packs/education/algebra-level-1/example-student-alice.yaml")
    orch = DSAOrchestrator(domain, profile, ledger_path="session.jsonl")
    contract, action = orch.process_turn(task_spec, evidence)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────
# Import ZPD Monitor via importlib
# (filename has hyphens — cannot use a regular import statement)
# This is the same pattern used in zpd-monitor-demo.py lines 22-36.
# ─────────────────────────────────────────────────────────────

_zpd_spec = importlib.util.spec_from_file_location(
    "zpd_monitor",
    os.path.join(os.path.dirname(__file__), "zpd-monitor-v0.2.py"),
)
_zpd_mod = importlib.util.module_from_spec(_zpd_spec)  # type: ignore[arg-type]
sys.modules["zpd_monitor"] = _zpd_mod
_zpd_spec.loader.exec_module(_zpd_mod)  # type: ignore[union-attr]

AffectState = _zpd_mod.AffectState
RecentWindow = _zpd_mod.RecentWindow
LearningState = _zpd_mod.LearningState
zpd_monitor_step = _zpd_mod.zpd_monitor_step
DEFAULT_PARAMS = _zpd_mod.DEFAULT_PARAMS


# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────

log = logging.getLogger("dsa_orchestrator")


# ─────────────────────────────────────────────────────────────
# CTL Hash Utilities
# (identical pattern to ctl-commitment-validator.py lines 49-60)
# ─────────────────────────────────────────────────────────────

def canonical_json(record: dict[str, Any]) -> bytes:
    """Canonical JSON: keys sorted, no whitespace, UTF-8."""
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def hash_record(record: dict[str, Any]) -> str:
    """Compute SHA-256 of a canonical CTL record."""
    return hashlib.sha256(canonical_json(record)).hexdigest()


# ─────────────────────────────────────────────────────────────
# Minimal YAML Loader (standard library only)
# ─────────────────────────────────────────────────────────────

def _strip_inline_comment(line: str) -> str:
    """Remove a trailing YAML comment (space + #) that is not inside quotes."""
    in_double = False
    in_single = False
    result: list[str] = []
    for i, ch in enumerate(line):
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == "#" and not in_double and not in_single:
            # Only a comment if preceded by whitespace (or at start)
            if i == 0 or line[i - 1] in (" ", "\t"):
                break
        result.append(ch)
    return "".join(result).rstrip()


def _parse_yaml_scalar(s: str) -> Any:
    """Parse a YAML scalar string into a Python value."""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() in ("null", "~", ""):
        return None
    # Inline sequence  [item, item, ...]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(p.strip()) for p in inner.split(",") if p.strip()]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s  # plain string


def _parse_yaml_lines(lines: list[str], pos: list[int]) -> Any:
    """
    Recursive parser for indented YAML blocks.

    `pos` is a one-element list used as a mutable index so recursive calls
    advance the shared position.  Returns the parsed Python value.
    """

    def skip_blank() -> None:
        while pos[0] < len(lines) and not lines[pos[0]].strip():
            pos[0] += 1

    def cur_indent() -> int:
        if pos[0] >= len(lines):
            return -1
        line = lines[pos[0]]
        stripped = line.lstrip()
        return len(line) - len(stripped) if stripped else -1

    skip_blank()
    if pos[0] >= len(lines):
        return None

    line0 = lines[pos[0]]
    stripped0 = line0.lstrip()
    base_indent = len(line0) - len(stripped0)

    if stripped0.startswith("- ") or stripped0 == "-":
        # ── List block ──────────────────────────────────────────
        result: list[Any] = []
        while pos[0] < len(lines):
            skip_blank()
            if pos[0] >= len(lines):
                break
            line = lines[pos[0]]
            stripped = line.lstrip()
            ind = len(line) - len(stripped)
            if ind != base_indent:
                break
            if not (stripped.startswith("- ") or stripped == "-"):
                break
            item_str = stripped[2:].strip()
            pos[0] += 1
            if item_str:
                result.append(_parse_yaml_scalar(item_str))
            else:
                # Nested mapping/sequence after bare dash
                skip_blank()
                if pos[0] < len(lines):
                    result.append(_parse_yaml_lines(lines, pos))
        return result
    else:
        # ── Mapping block ────────────────────────────────────────
        result_dict: dict[str, Any] = {}
        while pos[0] < len(lines):
            skip_blank()
            if pos[0] >= len(lines):
                break
            line = lines[pos[0]]
            stripped = line.lstrip()
            if not stripped:
                break
            ind = len(line) - len(stripped)
            if ind != base_indent:
                break
            if stripped.startswith("- "):
                break  # list encountered at this level — caller handles it
            if ":" not in stripped:
                pos[0] += 1
                continue
            colon = stripped.index(":")
            key = stripped[:colon].strip()
            val_str = stripped[colon + 1 :].strip()
            pos[0] += 1
            if val_str:
                result_dict[key] = _parse_yaml_scalar(val_str)
            else:
                # Nested block
                skip_blank()
                if pos[0] < len(lines):
                    next_line = lines[pos[0]]
                    next_stripped = next_line.lstrip()
                    next_ind = len(next_line) - len(next_stripped) if next_stripped else -1
                    if next_ind > base_indent:
                        result_dict[key] = _parse_yaml_lines(lines, pos)
                    else:
                        result_dict[key] = None
                else:
                    result_dict[key] = None
        return result_dict


def load_student_profile_yaml(path: str | Path) -> dict[str, Any]:
    """
    Load a student profile from a YAML file.

    Uses a minimal built-in parser (no external dependencies).  The parser
    handles nested dicts, lists, inline sequences, scalar types, and inline
    comments.  It is sufficient for the student profile format used by
    example-student-alice.yaml and any conforming student profile.
    """
    with open(path, encoding="utf-8") as fh:
        raw_lines = fh.readlines()

    lines: list[str] = []
    for raw in raw_lines:
        stripped = _strip_inline_comment(raw.rstrip("\n"))
        # Skip pure-comment and blank lines but keep blank lines to preserve
        # structure signals — _parse_yaml_lines already skips blanks.
        if stripped.lstrip().startswith("#"):
            lines.append("")
        else:
            lines.append(stripped)

    pos = [0]
    result = _parse_yaml_lines(lines, pos)
    return result if isinstance(result, dict) else {}


# ─────────────────────────────────────────────────────────────
# Domain Physics Loader
# ─────────────────────────────────────────────────────────────

def load_domain_physics(path: str | Path) -> dict[str, Any]:
    """Load domain physics from a JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────
# Invariant Evaluator Registry
#
# Maps each non-ZPD invariant id to the evidence field name and a
# check function.  The check function receives the raw evidence value
# and returns True if the invariant PASSES (i.e. is satisfied).
# ─────────────────────────────────────────────────────────────

def _check_equivalence_preserved(v: Any) -> bool:
    return bool(v)


def _check_no_illegal_operations(v: Any) -> bool:
    return v == [] or v is None


def _check_solution_verifies(v: Any) -> bool:
    return bool(v)


def _check_standard_method_preferred(v: Any) -> bool:
    return bool(v)


def _check_show_work_minimum(v: Any) -> bool:
    try:
        return int(v) >= 3
    except (TypeError, ValueError):
        return False


# invariant_id → (evidence_field_name, check_fn)
_INVARIANT_EVALUATORS: dict[str, tuple[str, Any]] = {
    "equivalence_preserved": ("equivalence_preserved", _check_equivalence_preserved),
    "no_illegal_operations": ("illegal_operations", _check_no_illegal_operations),
    "solution_verifies": ("substitution_check", _check_solution_verifies),
    "standard_method_preferred": ("method_recognized", _check_standard_method_preferred),
    "show_work_minimum": ("step_count", _check_show_work_minimum),
}

# ZPD invariants are delegated entirely to the ZPD monitor
_ZPD_INVARIANT_IDS = {"zpd_drift_minor", "zpd_drift_major"}


# ─────────────────────────────────────────────────────────────
# Action → Prompt Type Mapping
# ─────────────────────────────────────────────────────────────

_ACTION_TO_PROMPT_TYPE: dict[str | None, str] = {
    None: "task_presentation",
    "request_more_steps": "more_steps_request",
    "request_verification_retry": "verification_request",
    "request_method_justification": "method_justification_request",
    "zpd_scaffold": "scaffold",
    "zpd_intervene_or_escalate": "probe",
    "escalate": "probe",
}


# ─────────────────────────────────────────────────────────────
# DSAOrchestrator
# ─────────────────────────────────────────────────────────────

class DSAOrchestrator:
    """
    D.S.A. Action layer orchestrator.

    Connects Domain Physics → ZPD Monitor → CTL → Prompt Contract for a
    single student session.

    Attributes:
        domain      Domain physics dict loaded from JSON.
        profile     Student profile dict loaded from YAML (or equivalent).
        state       Current LearningState; updated each turn.
        session_id  UUID string identifying this session in the CTL.
    """

    def __init__(
        self,
        domain_physics: dict[str, Any],
        student_profile: dict[str, Any],
        ledger_path: str | Path,
        session_id: str | None = None,
    ) -> None:
        self.domain = domain_physics
        self.profile = student_profile
        self.ledger_path = Path(ledger_path)
        self.session_id = session_id or str(uuid.uuid4())
        self._prev_hash: str = "genesis"
        self._records: list[dict[str, Any]] = []

        # Diagnostics for the most recently processed turn (read-only for callers)
        self.last_invariant_results: list[dict[str, Any]] = []
        self.last_zpd_decision: dict[str, Any] = {}

        # Initialise learner state from student profile
        self.state = self._build_learning_state()

        # Write the session-open CommitmentRecord
        self._write_commitment_record()

    # ── State construction ────────────────────────────────────

    @property
    def ctl_records(self) -> list[dict[str, Any]]:
        """Read-only view of all CTL records written in this session."""
        return list(self._records)


    def _build_learning_state(self) -> LearningState:
        """Construct a LearningState from the loaded student profile dict."""
        ls = self.profile.get("learning_state", {})
        affect_data = ls.get("affect", {})
        mastery_data = ls.get("mastery", {})
        zpd_data = ls.get("zpd_band", {})
        rw_data = ls.get("recent_window", {})

        return LearningState(
            affect=AffectState(
                salience=float(affect_data.get("salience", 0.5)),
                valence=float(affect_data.get("valence", 0.0)),
                arousal=float(affect_data.get("arousal", 0.5)),
            ),
            mastery={k: float(v) for k, v in mastery_data.items()},
            zpd_band={
                "min_challenge": float(zpd_data.get("min_challenge", 0.3)),
                "max_challenge": float(zpd_data.get("max_challenge", 0.7)),
            },
            recent_window=RecentWindow(
                window_turns=int(rw_data.get("window_turns", 10)),
                attempts=int(rw_data.get("attempts", 0)),
                consecutive_incorrect=int(rw_data.get("consecutive_incorrect", 0)),
                hint_count=int(rw_data.get("hint_count", 0)),
                outside_pct=float(rw_data.get("outside_pct", 0.0)),
                consecutive_outside=int(rw_data.get("consecutive_outside", 0)),
                outside_flags=list(rw_data.get("outside_flags", [])),
                hint_flags=list(rw_data.get("hint_flags", [])),
            ),
            challenge=float(ls.get("challenge", 0.5)),
            uncertainty=float(ls.get("uncertainty", 0.5)),
        )

    # ── CTL record writers ────────────────────────────────────

    def _append_ctl_record(self, record: dict[str, Any]) -> None:
        """Append a record to the JSONL ledger and advance the hash chain."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            )
            fh.write("\n")
        self._prev_hash = hash_record(record)
        self._records.append(record)

    def _write_commitment_record(self) -> None:
        """Write the session-open CommitmentRecord to the CTL."""
        domain_id = self.domain.get("id", "unknown")
        domain_version = self.domain.get("version", "unknown")
        domain_authority = self.domain.get("domain_authority") or {}
        actor_id = domain_authority.get("pseudonymous_id", "unknown")
        record: dict[str, Any] = {
            "record_type": "CommitmentRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor_id,
            "actor_role": "domain_authority",
            "commitment_type": "domain_pack_activation",
            "subject_id": domain_id,
            "subject_version": domain_version,
            "subject_hash": "demo_session",
            "summary": (
                f"Session {self.session_id} opened — domain pack "
                f"{domain_id} v{domain_version}"
            ),
            "references": [],
            "metadata": {"session_id": self.session_id},
        }
        self._append_ctl_record(record)

    def _write_trace_event(
        self,
        task_spec: dict[str, Any],
        invariant_results: list[dict[str, Any]],
        zpd_decision: dict[str, Any],
        action: str | None,
        prompt_contract: dict[str, Any],
    ) -> None:
        """Append a TraceEvent record to the CTL for this turn."""
        record: dict[str, Any] = {
            "record_type": "TraceEvent",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event_type": "turn_processed",
            "actor_id": self.profile.get("student_id", "unknown"),
            "actor_role": "student",
            "decision": action,
            "decision_rationale": {
                "zpd_tier": zpd_decision.get("tier"),
                "drift_pct": zpd_decision.get("drift_pct"),
                "frustration": zpd_decision.get("frustration"),
                "invariant_failures": [
                    r["id"] for r in invariant_results if not r["passed"]
                ],
            },
            "task_id": task_spec.get("task_id", ""),
            "prompt_type": prompt_contract.get("prompt_type"),
            "metadata": {},
        }
        self._append_ctl_record(record)

    def _write_escalation_record(
        self,
        task_spec: dict[str, Any],
        zpd_decision: dict[str, Any],
        trigger: str,
    ) -> None:
        """Append an EscalationRecord to the CTL."""
        record: dict[str, Any] = {
            "record_type": "EscalationRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "actor_id": self.profile.get("student_id", "unknown"),
            "actor_role": "student",
            "status": "open",
            "trigger": trigger,
            "task_id": task_spec.get("task_id", ""),
            "zpd_decision": {
                "tier": zpd_decision.get("tier"),
                "frustration": zpd_decision.get("frustration"),
                "drift_pct": zpd_decision.get("drift_pct"),
            },
            "target_role": "teacher",
            "sla_minutes": 30,
            "metadata": {},
        }
        self._append_ctl_record(record)

    # ── Core decision logic ───────────────────────────────────

    def _evaluate_invariants(
        self, evidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Evaluate all non-ZPD invariants from the domain physics against the
        structured evidence dict.

        Returns a list of result dicts:
            {id, severity, passed, standing_order_on_violation, signal_type}

        Invariants whose required evidence field is absent are skipped with a
        log message (no false negatives from missing data).
        """
        results: list[dict[str, Any]] = []
        for inv in self.domain.get("invariants", []):
            inv_id: str = inv["id"]
            if inv_id in _ZPD_INVARIANT_IDS:
                continue  # Delegated to ZPD monitor

            evaluator = _INVARIANT_EVALUATORS.get(inv_id)
            if evaluator is None:
                log.debug("No evaluator for invariant %r — skipping", inv_id)
                continue

            field_name, check_fn = evaluator
            if field_name not in evidence:
                log.debug(
                    "Missing evidence field %r for invariant %r — skipping",
                    field_name,
                    inv_id,
                )
                continue

            value = evidence[field_name]
            try:
                passed = bool(check_fn(value))
            except Exception as exc:
                log.warning("Invariant %r check raised %r — skipping", inv_id, exc)
                continue

            results.append(
                {
                    "id": inv_id,
                    "severity": inv.get("severity", "warning"),
                    "passed": passed,
                    "standing_order_on_violation": inv.get("standing_order_on_violation"),
                    "signal_type": inv.get("signal_type"),
                }
            )
        return results

    def _resolve_action(
        self,
        invariant_results: list[dict[str, Any]],
        zpd_decision: dict[str, Any],
    ) -> tuple[str | None, bool]:
        """
        Determine the final action for this turn.

        Priority order:
          1. Critical invariant failure → its standing_order_on_violation.
          2. Warning invariant failure  → its standing_order_on_violation.
          3. No invariant failure       → ZPD monitor's decision["action"].

        Additionally, if the ZPD decision is zpd_intervene_or_escalate AND
        frustration is True, the second return value is True (escalate).

        Returns:
            (action, should_escalate)
        """
        # Critical failures first
        for result in invariant_results:
            if not result["passed"] and result["severity"] == "critical":
                return result["standing_order_on_violation"], False

        # Warning failures next
        for result in invariant_results:
            if not result["passed"] and result["severity"] == "warning":
                return result["standing_order_on_violation"], False

        # Fall through to ZPD monitor
        action = zpd_decision.get("action")
        frustration = bool(zpd_decision.get("frustration", False))
        should_escalate = (
            action == "zpd_intervene_or_escalate" and frustration
        )
        return action, should_escalate

    def _build_prompt_contract(
        self,
        task_spec: dict[str, Any],
        action: str | None,
        zpd_decision: dict[str, Any],
        standing_order_trigger: str | None,
    ) -> dict[str, Any]:
        """
        Build a prompt_contract dict conforming to prompt-contract-schema.json.

        The schema requires: prompt_type, domain_pack_id, domain_pack_version,
        task_id.  Additional optional fields are populated where available.
        """
        prompt_type = _ACTION_TO_PROMPT_TYPE.get(action, "task_presentation")

        preferences = self.profile.get("preferences", {})
        interests: list[str] = preferences.get("interests") or []
        theme: str | None = interests[0] if interests else None

        contract: dict[str, Any] = {
            "prompt_type": prompt_type,
            "domain_pack_id": self.domain.get("id", ""),
            "domain_pack_version": self.domain.get("version", ""),
            "task_id": task_spec.get("task_id", ""),
            "task_nominal_difficulty": float(
                task_spec.get("nominal_difficulty", zpd_decision.get("challenge", 0.5))
            ),
            "skills_targeted": list(task_spec.get("skills_required", [])),
            "theme": theme,
            "standing_order_trigger": standing_order_trigger,
            "references": [],
            "grounded": True,
        }

        if prompt_type == "hint":
            contract["hint_level"] = 1

        return contract

    # ── Public API ────────────────────────────────────────────

    def process_turn(
        self,
        task_spec: dict[str, Any],
        evidence: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """
        Process one session turn through the full D.S.A. loop.

        Args:
            task_spec: Current task specification.
                       Required keys:
                           task_id            — unique identifier string
                           nominal_difficulty — float 0..1
                           skills_required    — list of skill ID strings
                       Domain-specific evidence fields evaluated by the
                       invariant registry may also be present.
            evidence:  Structured evidence summary for this turn.
                       ZPD monitor keys (required):
                           correctness             — "correct"/"incorrect"/"partial"
                           hint_used               — bool
                           response_latency_sec    — float
                           frustration_marker_count — int
                           repeated_error          — bool
                           off_task_ratio          — float
                       Invariant evidence keys (optional; missing → skip):
                           equivalence_preserved   — bool
                           illegal_operations      — list (empty = no violations)
                           substitution_check      — bool
                           method_recognized       — bool
                           step_count              — int

        Returns:
            (prompt_contract, resolved_action)
            prompt_contract conforms to prompt-contract-schema.json.
            resolved_action is the string action taken (e.g. "request_more_steps")
            or "task_presentation" when no corrective action is needed.
        """
        # 1. Evaluate non-ZPD invariants
        invariant_results = self._evaluate_invariants(evidence)

        # 2. Step the ZPD monitor
        self.state, zpd_decision = zpd_monitor_step(self.state, task_spec, evidence)

        # Store diagnostics for the caller
        self.last_invariant_results = invariant_results
        self.last_zpd_decision = zpd_decision

        # 3. Resolve action
        action, should_escalate = self._resolve_action(invariant_results, zpd_decision)

        # Determine the standing order trigger label for the contract
        standing_order_trigger: str | None = None
        for result in invariant_results:
            if not result["passed"]:
                standing_order_trigger = result["standing_order_on_violation"]
                break
        if standing_order_trigger is None and action is not None:
            standing_order_trigger = action

        # 4. Build prompt contract
        prompt_contract = self._build_prompt_contract(
            task_spec, action, zpd_decision, standing_order_trigger
        )

        # 5. Append TraceEvent to CTL
        self._write_trace_event(
            task_spec, invariant_results, zpd_decision, action, prompt_contract
        )

        # 6. Append EscalationRecord if warranted
        if should_escalate:
            self._write_escalation_record(
                task_spec,
                zpd_decision,
                "zpd_intervene_or_escalate_with_frustration",
            )

        resolved_action = action if action is not None else "task_presentation"
        return prompt_contract, resolved_action
