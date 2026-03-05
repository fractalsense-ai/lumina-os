"""
dsa-orchestrator-demo.py — Project Lumina D.S.A. Orchestrator End-to-End Demo

Runs a scripted 10-turn algebra session showing the full D.S.A. loop:
  Domain Physics → ZPD Monitor → CTL → Prompt Contract

Each turn prints:
  - Invariant check results (pass/fail per invariant)
  - ZPD monitor decision (tier, action, challenge, drift_pct)
  - Resolved action
  - The full prompt_contract JSON that would be sent to the LLM
  - A simulated student-facing response based on prompt_type

The session includes a deliberate escalation event (frustration +
major ZPD drift).  After all turns the CTL hash chain is verified and
a session summary is printed.

Run:
    python reference-implementations/dsa-orchestrator-demo.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

# Allow running from repo root or from the reference-implementations directory
sys.path.insert(0, os.path.dirname(__file__))

# Import the orchestrator (same directory — regular import works because
# dsa-orchestrator.py registers itself in sys.modules via importlib internally)
import importlib.util as _ilu

_orch_spec = _ilu.spec_from_file_location(
    "dsa_orchestrator",
    os.path.join(os.path.dirname(__file__), "dsa-orchestrator.py"),
)
_orch_mod = _ilu.module_from_spec(_orch_spec)  # type: ignore[arg-type]
sys.modules["dsa_orchestrator"] = _orch_mod
_orch_spec.loader.exec_module(_orch_mod)  # type: ignore[union-attr]

DSAOrchestrator = _orch_mod.DSAOrchestrator
load_domain_physics = _orch_mod.load_domain_physics
load_student_profile_yaml = _orch_mod.load_student_profile_yaml
hash_record = _orch_mod.hash_record

# Import the education-domain ZPD monitor.
# The engine no longer loads this automatically; the education integration layer
# (i.e. this demo) wires it up explicitly and passes it to DSAOrchestrator.
# A non-education domain pack (e.g. agriculture) would simply omit these lines.
_zpd_spec = _ilu.spec_from_file_location(
    "zpd_monitor",
    os.path.join(os.path.dirname(__file__), "zpd-monitor-v0.2.py"),
)
_zpd_mod = _ilu.module_from_spec(_zpd_spec)  # type: ignore[arg-type]
sys.modules["zpd_monitor"] = _zpd_mod
_zpd_spec.loader.exec_module(_zpd_mod)  # type: ignore[union-attr]

AffectState = _zpd_mod.AffectState
RecentWindow = _zpd_mod.RecentWindow
LearningState = _zpd_mod.LearningState
zpd_monitor_step = _zpd_mod.zpd_monitor_step

# Also grab the CTL chain verifier from ctl-commitment-validator.py
_ctl_spec = _ilu.spec_from_file_location(
    "ctl_validator",
    os.path.join(os.path.dirname(__file__), "ctl-commitment-validator.py"),
)
_ctl_mod = _ilu.module_from_spec(_ctl_spec)  # type: ignore[arg-type]
sys.modules["ctl_validator"] = _ctl_mod
_ctl_spec.loader.exec_module(_ctl_mod)  # type: ignore[union-attr]

verify_chain = _ctl_mod.verify_chain
load_ledger = _ctl_mod.load_ledger


# ─────────────────────────────────────────────────────────────
# Repo path helpers
# ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent
_DOMAIN_PHYSICS_PATH = (
    _REPO_ROOT / "domain-packs" / "education" / "algebra-level-1" / "domain-physics.json"
)
_ALICE_PROFILE_PATH = (
    _REPO_ROOT / "domain-packs" / "education" / "algebra-level-1" / "example-student-alice.yaml"
)


# ─────────────────────────────────────────────────────────────
# Alice's profile (hard-coded fallback matching example-student-alice.yaml)
# Used if the YAML file cannot be parsed.
# ─────────────────────────────────────────────────────────────

_ALICE_PROFILE_FALLBACK: dict[str, Any] = {
    "student_id": "a3f8c2e1b4d7f9a0c5e2b8d1a6f3c7e4",
    "domain_id": "domain/edu/algebra-level-1/v1",
    "display_name": "Alice",
    "preferences": {
        "interests": ["space", "astronomy", "cooking"],
        "dislikes": ["sports_themes"],
        "preferred_explanation_style": "step_by_step",
        "language": "en",
    },
    "learning_state": {
        "affect": {"salience": 0.7, "valence": 0.2, "arousal": 0.6},
        "mastery": {
            "solve_one_variable": 0.52,
            "check_equivalence": 0.45,
            "show_work_steps": 0.60,
            "verify_solution": 0.38,
        },
        "challenge_band": {"min_challenge": 0.3, "max_challenge": 0.7},
        "recent_window": {
            "window_turns": 10,
            "attempts": 4,
            "consecutive_incorrect": 0,
            "hint_count": 2,
            "outside_pct": 0.2,
            "consecutive_outside": 0,
            "outside_flags": [False, False, True, False, False, False, False, False, True, False],
            "hint_flags": [True, False, True, False, False, False, False, False, False, False],
        },
        "challenge": 0.55,
        "uncertainty": 0.4,
    },
    "session_history": {
        "total_sessions": 3,
        "last_session_utc": "2026-03-01T15:30:00Z",
        "total_turns": 31,
    },
    "consent": {
        "magic_circle_accepted": True,
        "consent_timestamp_utc": "2026-02-20T09:00:00Z",
        "consent_version": "1.0.0",
        "guardian_consent": True,
    },
    "updated_utc": "2026-03-01T15:30:00Z",
}


# ─────────────────────────────────────────────────────────────
# Education-domain state builder
#
# Constructs a ZPD LearningState from a loaded student profile dict.
# This lives here (not in the engine) because LearningState is an
# education-domain type — the engine is domain-agnostic.
# ─────────────────────────────────────────────────────────────

def _build_learning_state_from_profile(profile: dict[str, Any]) -> "LearningState":
    """Build a ZPD LearningState from a loaded student profile dict."""
    ls = profile.get("learning_state", {})
    affect_data = ls.get("affect", {})
    mastery_data = ls.get("mastery", {})
    zpd_data = ls.get("challenge_band", {})
    rw_data = ls.get("recent_window", {})

    return LearningState(
        affect=AffectState(
            salience=float(affect_data.get("salience", 0.5)),
            valence=float(affect_data.get("valence", 0.0)),
            arousal=float(affect_data.get("arousal", 0.5)),
        ),
        mastery={k: float(v) for k, v in mastery_data.items()},
        challenge_band={
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


# ─────────────────────────────────────────────────────────────
# Simulated 10-turn session script
#
# Each entry: (description, task_spec, evidence)
#
# Evidence fields for ZPD monitor:
#   correctness, hint_used, response_latency_sec,
#   frustration_marker_count, repeated_error, off_task_ratio
#
# Evidence fields for domain invariants (all optional):
#   equivalence_preserved (bool)  — invariant: equivalence_preserved
#   illegal_operations    (list)  — invariant: no_illegal_operations
#   substitution_check    (bool)  — invariant: solution_verifies
#   method_recognized     (bool)  — invariant: standard_method_preferred
#   step_count            (int)   — invariant: show_work_minimum
# ─────────────────────────────────────────────────────────────

TURNS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    # ── Turn 1: Normal correct turn, all invariants pass ──────────────────
    (
        "Turn 1: Correct solution, all invariants satisfied",
        {
            "task_id": "alg1-task-001",
            "nominal_difficulty": 0.40,
            "skills_required": ["solve_one_variable", "show_work_steps"],
        },
        {
            "correctness": "correct",
            "hint_used": False,
            "response_latency_sec": 18.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            # Domain evidence
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": True,
            "method_recognized": True,
            "step_count": 4,
        },
    ),
    # ── Turn 2: Too few steps shown (show_work_minimum violation) ─────────
    (
        "Turn 2: Correct answer but only 2 steps shown (show_work_minimum fails)",
        {
            "task_id": "alg1-task-002",
            "nominal_difficulty": 0.42,
            "skills_required": ["solve_one_variable", "show_work_steps"],
        },
        {
            "correctness": "correct",
            "hint_used": False,
            "response_latency_sec": 12.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            # Domain evidence
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": True,
            "method_recognized": True,
            "step_count": 2,          # ← violation: must be >= 3
        },
    ),
    # ── Turn 3: Critical — equivalence broken in one step ─────────────────
    (
        "Turn 3: Equivalence not preserved in a step (critical invariant fails)",
        {
            "task_id": "alg1-task-003",
            "nominal_difficulty": 0.45,
            "skills_required": ["solve_one_variable", "check_equivalence"],
        },
        {
            "correctness": "incorrect",
            "hint_used": False,
            "response_latency_sec": 35.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            # Domain evidence
            "equivalence_preserved": False,   # ← critical violation
            "illegal_operations": [],
            "substitution_check": False,
            "method_recognized": True,
            "step_count": 3,
        },
    ),
    # ── Turn 4: Novel method (non-standard, triggers justification request) ─
    (
        "Turn 4: Non-standard method used (standard_method_preferred fails)",
        {
            "task_id": "alg1-task-004",
            "nominal_difficulty": 0.48,
            "skills_required": ["solve_one_variable", "check_equivalence"],
        },
        {
            "correctness": "correct",
            "hint_used": False,
            "response_latency_sec": 22.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            # Domain evidence
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": True,
            "method_recognized": False,   # ← novel method flag
            "step_count": 5,
        },
    ),
    # ── Turn 5: Verification fails (critical) ────────────────────────────
    (
        "Turn 5: Solution does not verify when substituted back (critical fails)",
        {
            "task_id": "alg1-task-005",
            "nominal_difficulty": 0.50,
            "skills_required": ["solve_one_variable", "verify_solution"],
        },
        {
            "correctness": "incorrect",
            "hint_used": True,
            "response_latency_sec": 45.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            # Domain evidence
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": False,  # ← critical violation
            "method_recognized": True,
            "step_count": 3,
        },
    ),
    # ── Turn 6: Harder task, incorrect — pushing toward ZPD upper edge ────
    (
        "Turn 6: Harder task, incorrect — challenge nearing ZPD upper edge",
        {
            "task_id": "alg1-task-006",
            "nominal_difficulty": 0.72,
            "skills_required": ["solve_one_variable", "verify_solution"],
        },
        {
            "correctness": "incorrect",
            "hint_used": False,
            "response_latency_sec": 52.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.05,
            # Domain evidence (no invariant failures)
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": False,
            "method_recognized": True,
            "step_count": 4,
        },
    ),
    # ── Turn 7: Outside ZPD again, frustration emerging ──────────────────
    (
        "Turn 7: Outside ZPD, incorrect with frustration signal",
        {
            "task_id": "alg1-task-007",
            "nominal_difficulty": 0.75,
            "skills_required": ["solve_one_variable", "verify_solution"],
        },
        {
            "correctness": "incorrect",
            "hint_used": True,
            "response_latency_sec": 68.0,
            "frustration_marker_count": 1,
            "repeated_error": True,
            "off_task_ratio": 0.10,
            # Domain evidence
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": False,
            "method_recognized": True,
            "step_count": 2,       # also a show_work violation
        },
    ),
    # ── Turn 8: Still outside ZPD, frustration escalating ─────────────────
    (
        "Turn 8: Outside ZPD, frustration rising — major drift building",
        {
            "task_id": "alg1-task-008",
            "nominal_difficulty": 0.78,
            "skills_required": ["solve_one_variable", "verify_solution"],
        },
        {
            "correctness": "incorrect",
            "hint_used": True,
            "response_latency_sec": 72.0,
            "frustration_marker_count": 2,
            "repeated_error": True,
            "off_task_ratio": 0.15,
            # No invariant-specific evidence this turn
        },
    ),
    # ── Turn 9: ESCALATION — frustration + major drift ─────────────────────
    (
        "Turn 9: *** ESCALATION *** — persistent frustration + major ZPD drift",
        {
            "task_id": "alg1-task-009",
            "nominal_difficulty": 0.80,
            "skills_required": ["solve_one_variable", "verify_solution"],
        },
        {
            "correctness": "incorrect",
            "hint_used": True,
            "response_latency_sec": 85.0,
            "frustration_marker_count": 3,
            "repeated_error": True,
            "off_task_ratio": 0.20,
            # No invariant-specific evidence this turn
        },
    ),
    # ── Turn 10: Recovery — easy scaffolded task, back in ZPD ─────────────
    (
        "Turn 10: Recovery — easy task, back inside ZPD, all invariants pass",
        {
            "task_id": "alg1-task-010",
            "nominal_difficulty": 0.38,
            "skills_required": ["solve_one_variable", "show_work_steps"],
        },
        {
            "correctness": "correct",
            "hint_used": False,
            "response_latency_sec": 20.0,
            "frustration_marker_count": 0,
            "repeated_error": False,
            "off_task_ratio": 0.0,
            # Domain evidence
            "equivalence_preserved": True,
            "illegal_operations": [],
            "substitution_check": True,
            "method_recognized": True,
            "step_count": 4,
        },
    ),
]


# ─────────────────────────────────────────────────────────────
# Simulated student-facing responses
# ─────────────────────────────────────────────────────────────

def _simulate_student_response(contract: dict[str, Any]) -> str:
    """
    Produce a short text showing what the student would see for this
    prompt_type.  This is a pure simulation — in production the LLM
    Conversational Interface would generate this from the prompt_contract.
    """
    pt = contract.get("prompt_type", "task_presentation")
    theme = contract.get("theme") or "math"
    task_id = contract.get("task_id", "unknown")
    difficulty = contract.get("task_nominal_difficulty", 0.5)

    messages: dict[str, str] = {
        "task_presentation": (
            f"[{theme.upper()} theme] Here is your next equation to solve "
            f"(task {task_id}, difficulty {difficulty:.2f}). Show each step."
        ),
        "more_steps_request": (
            "Your answer looks interesting, but I need to see each step of "
            "your working. Can you write out every transformation you applied?"
        ),
        "verification_request": (
            "Let's check the solution. Substitute your answer back into the "
            "original equation and show me that both sides are equal."
        ),
        "method_justification_request": (
            "That's an unusual approach. Can you explain the reasoning behind "
            "each step you used? I'd like to understand your method."
        ),
        "scaffold": (
            f"Let's step back for a moment. Here is a slightly easier problem "
            f"(difficulty {difficulty:.2f}) to help build momentum."
        ),
        "probe": (
            "Before we continue, I want to check in. Can you explain what the "
            "goal of this equation-solving step is?"
        ),
        "hint": (
            "Here is a small nudge: think about what operation would isolate "
            "the variable on one side of the equation."
        ),
        "boss_challenge": (
            "You have been doing well. This is a challenge problem — give it "
            "your best effort without hints."
        ),
        "session_close_summary": (
            "Great work today. Here is a summary of what you practised and "
            "where you made progress."
        ),
    }
    return messages.get(pt, f"[{pt}]")


# ─────────────────────────────────────────────────────────────
# Print helpers
# ─────────────────────────────────────────────────────────────

def _sep(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _print_invariant_results(results: list[dict[str, Any]]) -> None:
    if not results:
        print("  Invariants: (no evidence fields present this turn)")
        return
    for r in results:
        icon = "✓" if r["passed"] else "✗"
        sev = r["severity"].upper()[:4]
        note = ""
        if not r["passed"]:
            note = f"  → {r['standing_order_on_violation']}"
            if r.get("signal_type"):
                note += f"  [{r['signal_type']}]"
        print(f"  [{icon}] {r['id']:<30} ({sev}){note}")


# ─────────────────────────────────────────────────────────────
# Main demo
# ─────────────────────────────────────────────────────────────

def run_demo() -> None:
    _sep("═")
    print("  Project Lumina — D.S.A. Orchestrator Demo (v0.1.0)")
    print("  Domain: Algebra Level 1  |  Student: Alice (example)")
    _sep("═")

    # ── Load domain physics ───────────────────────────────────
    print(f"\nLoading domain physics from:")
    print(f"  {_DOMAIN_PHYSICS_PATH}")
    domain = load_domain_physics(_DOMAIN_PHYSICS_PATH)
    print(f"  → {domain['id']}  v{domain['version']}")
    print(f"  → {len(domain['invariants'])} invariants, "
          f"{len(domain['standing_orders'])} standing orders")

    # ── Load student profile ──────────────────────────────────
    print(f"\nLoading student profile from:")
    print(f"  {_ALICE_PROFILE_PATH}")
    try:
        profile = load_student_profile_yaml(_ALICE_PROFILE_PATH)
        if not profile.get("student_id"):
            raise ValueError("student_id missing — fallback to hard-coded profile")
        print(f"  → Student: {profile.get('display_name', 'Unknown')} "
              f"(id={profile.get('student_id', '?')[:8]}...)")
    except Exception as exc:
        print(f"  ! YAML parse issue ({exc}); using hard-coded Alice profile")
        profile = _ALICE_PROFILE_FALLBACK

    # Record initial mastery for the session summary
    initial_mastery = dict(
        profile.get("learning_state", {}).get("mastery", {})
    )

    # ── Temp ledger ───────────────────────────────────────────
    ledger_file = tempfile.NamedTemporaryFile(
        mode="w", suffix="-ctl-demo.jsonl", delete=False, encoding="utf-8"
    )
    ledger_path = Path(ledger_file.name)
    ledger_file.close()
    print(f"\nCTL ledger: {ledger_path}\n")

    # ── Create orchestrator (writes CommitmentRecord) ─────────
    # Wire up the education-domain ZPD monitor explicitly.
    # A non-education domain (e.g. agriculture) would omit sensor_step_fn
    # and initial_state, and the engine would skip the sensor step entirely.
    session_id = str(uuid.uuid4())
    initial_state = _build_learning_state_from_profile(profile)
    orch = DSAOrchestrator(
        domain_physics=domain,
        student_profile=profile,
        ledger_path=ledger_path,
        session_id=session_id,
        sensor_step_fn=zpd_monitor_step,
        initial_state=initial_state,
    )

    _sep()
    print(f"Session {session_id[:8]}... opened")
    print(f"Initial mastery: "
          f"solve={initial_mastery.get('solve_one_variable', 0):.2f}  "
          f"equiv={initial_mastery.get('check_equivalence', 0):.2f}  "
          f"steps={initial_mastery.get('show_work_steps', 0):.2f}  "
          f"verify={initial_mastery.get('verify_solution', 0):.2f}")
    _sep()

    # ── Run turns ─────────────────────────────────────────────
    total_drift_events = 0
    total_escalations = 0

    for turn_num, (description, task_spec, evidence) in enumerate(TURNS, start=1):
        print(f"\n[Turn {turn_num:02d}] {description}")
        _sep("·")

        # Snapshot invariant-relevant evidence fields for display
        inv_evidence_preview = {
            k: evidence[k]
            for k in ("equivalence_preserved", "illegal_operations",
                      "substitution_check", "method_recognized", "step_count")
            if k in evidence
        }

        # Process through the orchestrator
        contract, resolved_action = orch.process_turn(task_spec, evidence)

        # Retrieve diagnostics stored by the orchestrator
        inv_results_display = orch.last_invariant_results
        zpd_decision = orch.last_sensor_decision

        # Detect drift/escalation events
        if resolved_action in ("zpd_scaffold", "zpd_intervene_or_escalate"):
            total_drift_events += 1
        escalation_records = [
            r for r in orch.ctl_records
            if r.get("record_type") == "EscalationRecord"
        ]
        if len(escalation_records) > total_escalations:
            total_escalations = len(escalation_records)

        # ── Print invariant results ───────────────────────────
        print("\n  INVARIANT CHECKS:")
        _print_invariant_results(inv_results_display)
        if inv_evidence_preview:
            print(f"  Evidence used: {inv_evidence_preview}")
        else:
            print("  Evidence used: (no domain-invariant fields in evidence)")

        # ── Print ZPD decision ────────────────────────────────
        print(f"\n  ZPD MONITOR:")
        tier = zpd_decision.get("tier", "ok")
        tier_icon = {"ok": "✓ ok", "minor": "⚠ MINOR", "major": "⚡ MAJOR"}.get(tier, tier)
        rw = orch.state.recent_window
        print(f"    Challenge  : {zpd_decision.get('challenge', orch.state.challenge):.3f}")
        print(f"    DriftPct   : {zpd_decision.get('drift_pct', rw.outside_pct):.2f}  "
              f"ConsecOutside: {rw.consecutive_outside}")
        print(f"    Tier       : {tier_icon}")
        if zpd_decision.get("frustration"):
            print(f"    ** FRUSTRATION FLAG **")

        # ── Resolved action ───────────────────────────────────
        action_icon = {
            "task_presentation": "→",
            "more_steps_request": "⚑",
            "verification_request": "⚑",
            "method_justification_request": "⚑",
            "scaffold": "⚠",
            "probe": "⚡",
        }.get(contract.get("prompt_type", ""), "→")

        print(f"\n  RESOLVED ACTION : {action_icon} {resolved_action}")
        print(f"  PROMPT TYPE     : {contract.get('prompt_type')}")

        # ── Full prompt contract ──────────────────────────────
        print("\n  PROMPT CONTRACT (JSON):")
        contract_json = json.dumps(contract, indent=4, ensure_ascii=False)
        for line in contract_json.splitlines():
            print(f"    {line}")

        # ── Simulated student-facing response ─────────────────
        student_msg = _simulate_student_response(contract)
        print(f"\n  STUDENT SEES:\n    \"{student_msg}\"")

        # ── Mastery snapshot ──────────────────────────────────
        m = orch.state.mastery
        print(f"\n  Mastery: "
              f"solve={m.get('solve_one_variable', 0):.3f}  "
              f"equiv={m.get('check_equivalence', 0):.3f}  "
              f"steps={m.get('show_work_steps', 0):.3f}  "
              f"verify={m.get('verify_solution', 0):.3f}")

        _sep()

    # ── CTL chain verification ────────────────────────────────
    print("\nVerifying CTL hash chain...")
    records = load_ledger(ledger_path)
    result = verify_chain(records)
    if result["intact"]:
        print(f"  Chain integrity: INTACT ✓  ({result['records_checked']} records verified)")
    else:
        print(f"  Chain integrity: BROKEN ✗")
        print(f"  Error: {result['error']}")

    # ── Session summary ───────────────────────────────────────
    final_mastery = orch.state.mastery
    print()
    _sep("═")
    print("  SESSION SUMMARY")
    _sep("═")
    print(f"  Session ID  : {session_id[:8]}...")
    print(f"  Turns run   : {len(TURNS)}")
    print(f"  CTL records : {len(records)}")
    print()
    print("  Mastery deltas (initial → final):")
    for skill in sorted(initial_mastery):
        init_v = initial_mastery[skill]
        final_v = final_mastery.get(skill, init_v)
        delta = final_v - init_v
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
        print(f"    {skill:<26} {init_v:.3f} → {final_v:.3f}  {arrow}{abs(delta):.3f}")
    print()

    # Count event types in CTL
    trace_events = [r for r in records if r.get("record_type") == "TraceEvent"]
    escalation_records = [r for r in records if r.get("record_type") == "EscalationRecord"]
    commitment_records = [r for r in records if r.get("record_type") == "CommitmentRecord"]
    all_drift = [
        r for r in trace_events
        if r.get("decision") in ("zpd_scaffold", "zpd_intervene_or_escalate")
    ]

    print(f"  CommitmentRecords : {len(commitment_records)}")
    print(f"  TraceEvents       : {len(trace_events)}")
    print(f"  EscalationRecords : {len(escalation_records)}")
    print(f"  Drift actions     : {len(all_drift)}")

    if escalation_records:
        print()
        print("  Escalation events:")
        for esc in escalation_records:
            print(f"    - {esc.get('trigger')}  "
                  f"(task={esc.get('task_id')}, sla={esc.get('sla_minutes')} min)")

    print()
    print(f"  Final affect: "
          f"S={orch.state.affect.salience:.2f} "
          f"V={orch.state.affect.valence:+.2f} "
          f"A={orch.state.affect.arousal:.2f}")
    print(f"  ZPD window  : outside_pct={orch.state.recent_window.outside_pct:.2f}  "
          f"consecutive_outside={orch.state.recent_window.consecutive_outside}")
    _sep("═")


if __name__ == "__main__":
    run_demo()
