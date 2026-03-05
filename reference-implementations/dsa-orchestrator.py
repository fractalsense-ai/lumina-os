"""
dsa-orchestrator.py — Project Lumina D.S.A. Orchestrator Reference Implementation

Version: 0.2.0
Conforms to: specs/dsa-framework-v1.md
             standards/causal-trace-ledger-v1.md

Implements the Action layer of the D.S.A. framework, connecting:
    Domain Physics → (optional domain sensor) → CTL → Prompt Contract

The orchestrator:
  1. Loads Domain Physics (JSON) defining invariants and standing orders.
  2. Holds the current sensor state (initialised by the caller, or None).
  3. For every session turn:
       a. Evaluates non-delegated invariants against structured evidence by
          interpreting the ``check`` expression declared in each invariant
          definition.  No domain-specific logic is baked into the engine.
       b. Steps any registered domain sensor to obtain an updated state and
          a decision dict.  If no sensor is registered the decision is empty.
       c. Resolves the final action (invariant failures trump sensor drift).
       d. Builds a prompt_contract JSON object conforming to the domain schema.
       e. Appends a hash-chained TraceEvent (and, when needed, an
          EscalationRecord) to the Causal Trace Ledger (CTL).
  4. Opens the session with a CommitmentRecord in the CTL.

Invariant evaluation (domain-pack-driven):
  Each invariant in the domain-pack may carry a ``check`` field whose value
  is a simple predicate expression referencing flat evidence-dict keys:

    ``<field>``                  — truthy check on evidence[field]
    ``<field> == <literal>``     — equality check  (supports [] / true / false)
    ``<field> != <literal>``     — inequality check
    ``<field> >= <number>``      — numeric comparison  (also >, <, <=)

  Invariants marked with ``"handled_by": "<subsystem>"`` are skipped here
  and delegated entirely to the registered domain sensor (or ignored when no
  sensor is registered).  This mechanism is domain-agnostic: an agriculture
  domain can define ``soil_moisture_drift_minor`` with
  ``handled_by: soil_health_monitor`` using the same pattern.

Design constraints:
  - Standard library only (no external dependencies).
  - All CTL records are hash-chained with SHA-256 canonical JSON, exactly as
    implemented in ctl-commitment-validator.py.
  - No domain-specific sensor (e.g. ZPD monitor) is imported or required by
    the engine.  Domain integrations wire up their sensors externally and pass
    them in via ``sensor_step_fn`` / ``initial_state``.

Usage:
    from dsa_orchestrator import DSAOrchestrator, load_domain_physics, load_student_profile_yaml
    domain = load_domain_physics("domain-packs/education/algebra-level-1/domain-physics.json")
    profile = load_student_profile_yaml("domain-packs/education/algebra-level-1/example-student-alice.yaml")
    # For a domain with no sensor:
    orch = DSAOrchestrator(domain, profile, ledger_path="session.jsonl")
    # For the education domain — wire up the ZPD monitor externally:
    orch = DSAOrchestrator(domain, profile, ledger_path="session.jsonl",
                           sensor_step_fn=zpd_monitor_step, initial_state=initial_learning_state)
    contract, action = orch.process_turn(task_spec, evidence)
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


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
# Domain-pack-driven invariant check evaluator
#
# Evaluates the ``check`` predicate declared in each domain-pack invariant
# definition against the flat evidence dict passed in by the caller.
#
# Supported expression forms:
#   <field>                  – truthy check on evidence[field]
#   <field> == <literal>     – equality   ([] / true / false / number / string)
#   <field> != <literal>     – inequality
#   <field> >= <number>      – numeric GTE (also >, <, <=)
#
# Returns True  — invariant passes.
#         False — invariant fails.
#         None  — required evidence field is absent; caller should skip.
# ─────────────────────────────────────────────────────────────

def _parse_check_literal(raw: str) -> Any:
    """Parse the right-hand side literal of a check expression."""
    raw = raw.strip()
    if raw == "[]":
        return []
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    log.debug("Check literal %r treated as plain string", raw)
    return raw


def _evaluate_check_expr(check_expr: str, evidence: dict[str, Any]) -> bool | None:
    """
    Evaluate a domain-pack ``check`` expression against the evidence dict.

    The expression must reference a flat evidence-dict key directly.
    Supported forms::

        equivalence_preserved          # truthy
        illegal_operations == []       # equality with empty list
        substitution_check             # truthy
        method_recognized              # truthy
        step_count >= 3                # numeric comparison

    Expressions are tokenised by whitespace into at most three parts
    (field, operator, right-hand-side literal).  String literals that
    contain spaces are therefore **not** supported as right-hand-side values.

    Returns True if the invariant passes, False if it fails, or None when
    the referenced evidence field is absent (caller skips the invariant).
    """
    tokens = check_expr.strip().split(None, 2)

    if len(tokens) == 1:
        # Bare field name — truthy check
        field = tokens[0]
        if field not in evidence:
            return None
        return bool(evidence[field])

    if len(tokens) == 3:
        field, op, raw_val = tokens
        if field not in evidence:
            return None
        ev_val = evidence[field]
        rhs = _parse_check_literal(raw_val)
        if op == "==":
            return ev_val == rhs
        if op == "!=":
            return ev_val != rhs
        if op == ">=":
            return ev_val >= rhs
        if op == "<=":
            return ev_val <= rhs
        if op == ">":
            return ev_val > rhs
        if op == "<":
            return ev_val < rhs
        log.warning("Unknown operator %r in check expression %r", op, check_expr)
        return None

    log.warning("Cannot parse check expression %r — skipping invariant", check_expr)
    return None


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

    Connects Domain Physics → (optional domain sensor) → CTL → Prompt Contract
    for a single session.

    Attributes:
        domain      Domain physics dict loaded from JSON.
        profile     Student profile dict loaded from YAML (or equivalent).
        state       Current sensor state supplied by the caller; updated each
                    turn when a ``sensor_step_fn`` is registered.
        session_id  UUID string identifying this session in the CTL.
    """

    def __init__(
        self,
        domain_physics: dict[str, Any],
        student_profile: dict[str, Any],
        ledger_path: str | Path,
        session_id: str | None = None,
        sensor_step_fn: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
        initial_state: Any | None = None,
    ) -> None:
        """
        Initialise the orchestrator.

        Args:
            domain_physics:  Domain physics dict (from ``load_domain_physics``).
            student_profile: Student profile dict (from ``load_student_profile_yaml``
                             or equivalent).
            ledger_path:     Path to the JSONL CTL ledger file.
            session_id:      Optional session UUID; generated if omitted.
            sensor_step_fn:  Optional domain sensor callable with signature
                             ``(state, task_spec, evidence) -> (new_state, decision_dict)``.
                             Pass ``None`` (default) for domain packs that declare
                             no sensor subsystem.
            initial_state:   Initial sensor state to pass to ``sensor_step_fn`` on
                             the first turn.  Ignored when ``sensor_step_fn`` is
                             ``None``.  For the education domain this is a
                             ``LearningState`` object built by the caller from the
                             student profile.
        """
        self.domain = domain_physics
        self.profile = student_profile
        self.ledger_path = Path(ledger_path)
        self.session_id = session_id or str(uuid.uuid4())
        self._prev_hash: str = "genesis"
        self._records: list[dict[str, Any]] = []
        self._sensor_step_fn = sensor_step_fn

        # Diagnostics for the most recently processed turn (read-only for callers)
        self.last_invariant_results: list[dict[str, Any]] = []
        self.last_zpd_decision: dict[str, Any] = {}

        # Sensor state: managed externally; the engine treats it as opaque.
        self.state = initial_state

        # Write the session-open CommitmentRecord
        self._write_commitment_record()

    # ── State construction ────────────────────────────────────

    @property
    def ctl_records(self) -> list[dict[str, Any]]:
        """Read-only view of all CTL records written in this session."""
        return list(self._records)

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
        Evaluate all domain-pack invariants against the structured evidence dict.

        Invariants marked with ``"handled_by": "zpd_monitor"`` are skipped here
        and delegated entirely to the ZPD monitor.

        Each remaining invariant is evaluated by parsing its ``check`` field —
        a simple predicate expression whose operand is a flat key in the evidence
        dict (see ``_evaluate_check_expr`` for supported syntax).

        Returns a list of result dicts:
            {id, severity, passed, standing_order_on_violation, signal_type}

        Invariants whose ``check`` field is absent or whose evidence field is
        missing from the supplied dict are skipped with a log message (no false
        negatives from missing data).
        """
        results: list[dict[str, Any]] = []
        for inv in self.domain.get("invariants", []):
            inv_id: str = inv["id"]

            # Skip invariants delegated to another subsystem (e.g. ZPD monitor)
            if inv.get("handled_by"):
                continue

            check_expr: str | None = inv.get("check")
            if not check_expr:
                log.debug("No check expression for invariant %r — skipping", inv_id)
                continue

            try:
                result = _evaluate_check_expr(check_expr, evidence)
            except Exception as exc:
                log.warning("Invariant %r check raised %r — skipping", inv_id, exc)
                continue

            if result is None:
                log.debug(
                    "Missing evidence for invariant %r (check=%r) — skipping",
                    inv_id,
                    check_expr,
                )
                continue

            results.append(
                {
                    "id": inv_id,
                    "severity": inv.get("severity", "warning"),
                    "passed": result,
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
            evidence:  Structured evidence summary for this turn.
                       Domain-invariant evidence keys are defined by the ``check``
                       expressions in the loaded domain-pack.  Missing fields are
                       silently skipped (no false negatives).
                       Sensor-specific evidence keys (e.g. for the ZPD monitor in
                       the education domain) are passed through unchanged to
                       ``sensor_step_fn`` when one is registered.
                       For the algebra-level-1 pack with the ZPD monitor the
                       expected keys include:
                           correctness             — "correct"/"incorrect"/"partial"
                           hint_used               — bool
                           response_latency_sec    — float
                           frustration_marker_count — int
                           repeated_error          — bool
                           off_task_ratio          — float
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
        # 1. Evaluate non-delegated invariants
        invariant_results = self._evaluate_invariants(evidence)

        # 2. Step any registered domain sensor (e.g. ZPD monitor for education).
        #    If no sensor is registered the decision dict is empty and the
        #    orchestrator falls back to invariant-only logic.
        if self._sensor_step_fn is not None:
            self.state, zpd_decision = self._sensor_step_fn(
                self.state, task_spec, evidence
            )
        else:
            zpd_decision: dict[str, Any] = {}

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
