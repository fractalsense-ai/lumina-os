"""
zpd-monitor-demo.py — Project Lumina ZPD Monitor Demonstration

Runs a simulated 20-turn algebra session showing:
  - Normal turns within ZPD (ok tier)
  - Minor drift detection (zpd_scaffold)
  - Major drift detection (zpd_intervene_or_escalate)
  - Frustration detection
  - Mastery progression

Run:
    python reference-implementations/zpd-monitor-demo.py
"""

import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.dirname(__file__))

# Import from the monitor module (rename to valid Python module name)
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "zpd_monitor",
    os.path.join(os.path.dirname(__file__), "zpd-monitor-v0.2.py"),
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["zpd_monitor"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

AffectState = _mod.AffectState
RecentWindow = _mod.RecentWindow
LearningState = _mod.LearningState
zpd_monitor_step = _mod.zpd_monitor_step
DEFAULT_PARAMS = _mod.DEFAULT_PARAMS


# ─────────────────────────────────────────────────────────────
# Simulated Session
# ─────────────────────────────────────────────────────────────

TURNS = [
    # (description, task_spec, evidence)
    (
        "Turn 1: Easy equation, correct, no hint",
        {"nominal_difficulty": 0.35, "skills_required": ["solve_one_variable", "show_work_steps"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 15.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 2: Easy equation, correct, with hint",
        {"nominal_difficulty": 0.35, "skills_required": ["solve_one_variable"]},
        {"correctness": "correct", "hint_used": True, "response_latency_sec": 25.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 3: Medium equation, partial",
        {"nominal_difficulty": 0.5, "skills_required": ["solve_one_variable", "check_equivalence"]},
        {"correctness": "partial", "hint_used": False, "response_latency_sec": 40.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 4: Medium equation, correct, no hint",
        {"nominal_difficulty": 0.5, "skills_required": ["solve_one_variable", "check_equivalence"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 20.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 5: Harder equation (pushing toward upper ZPD), incorrect",
        {"nominal_difficulty": 0.72, "skills_required": ["solve_one_variable", "verify_solution"]},
        {"correctness": "incorrect", "hint_used": False, "response_latency_sec": 55.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.05},
    ),
    (
        "Turn 6: Harder equation, incorrect again (outside ZPD, above)",
        {"nominal_difficulty": 0.75, "skills_required": ["solve_one_variable", "verify_solution"]},
        {"correctness": "incorrect", "hint_used": True, "response_latency_sec": 65.0,
         "frustration_marker_count": 1, "repeated_error": True, "off_task_ratio": 0.1},
    ),
    (
        "Turn 7: Still hard, incorrect, frustration signal (outside ZPD)",
        {"nominal_difficulty": 0.78, "skills_required": ["solve_one_variable", "verify_solution"]},
        {"correctness": "incorrect", "hint_used": True, "response_latency_sec": 70.0,
         "frustration_marker_count": 2, "repeated_error": True, "off_task_ratio": 0.15},
    ),
    (
        "Turn 8: Scaffolded — easier problem offered (back in ZPD)",
        {"nominal_difficulty": 0.45, "skills_required": ["solve_one_variable"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 18.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 9: Medium difficulty, correct",
        {"nominal_difficulty": 0.50, "skills_required": ["solve_one_variable", "check_equivalence"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 22.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 10: Medium difficulty, correct, no hint",
        {"nominal_difficulty": 0.52, "skills_required": ["solve_one_variable", "check_equivalence"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 19.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 11: Gradually increasing — still in ZPD",
        {"nominal_difficulty": 0.58, "skills_required": ["check_equivalence", "verify_solution"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 25.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 12: Challenge increasing, correct with hint",
        {"nominal_difficulty": 0.62, "skills_required": ["check_equivalence", "verify_solution"]},
        {"correctness": "correct", "hint_used": True, "response_latency_sec": 30.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 13: Near upper ZPD, partial",
        {"nominal_difficulty": 0.65, "skills_required": ["solve_one_variable", "verify_solution"]},
        {"correctness": "partial", "hint_used": False, "response_latency_sec": 45.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 14: Verification task, correct, no hint",
        {"nominal_difficulty": 0.55, "skills_required": ["verify_solution", "show_work_steps"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 12.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
    (
        "Turn 15: Full multi-step equation, correct",
        {"nominal_difficulty": 0.60, "skills_required": ["solve_one_variable", "check_equivalence", "show_work_steps"]},
        {"correctness": "correct", "hint_used": False, "response_latency_sec": 35.0,
         "frustration_marker_count": 0, "repeated_error": False, "off_task_ratio": 0.0},
    ),
]


def print_separator(char: str = "─", width: int = 70) -> None:
    print(char * width)


def run_demo() -> None:
    print_separator("═")
    print("  Project Lumina — ZPD Monitor Demo (v0.2)")
    print("  Domain: Algebra Level 1  |  Student: Alice (example)")
    print_separator("═")

    # Initial state (matches example-student-alice.yaml)
    state = LearningState(
        affect=AffectState(salience=0.7, valence=0.2, arousal=0.6),
        mastery={
            "solve_one_variable": 0.52,
            "check_equivalence": 0.45,
            "show_work_steps": 0.60,
            "verify_solution": 0.38,
        },
        zpd_band={"min_challenge": 0.3, "max_challenge": 0.7},
        recent_window=RecentWindow(window_turns=10),
        challenge=0.55,
        uncertainty=0.4,
    )

    print(f"\nInitial state:")
    print(f"  Mastery:     solve={state.mastery['solve_one_variable']:.2f}  "
          f"equiv={state.mastery['check_equivalence']:.2f}  "
          f"steps={state.mastery['show_work_steps']:.2f}  "
          f"verify={state.mastery['verify_solution']:.2f}")
    print(f"  ZPD band:    [{state.zpd_band['min_challenge']:.1f}, {state.zpd_band['max_challenge']:.1f}]")
    print(f"  Affect:      S={state.affect.salience:.2f} V={state.affect.valence:+.2f} A={state.affect.arousal:.2f}")
    print()

    for i, (description, task_spec, evidence) in enumerate(TURNS, start=1):
        state, decision = zpd_monitor_step(state, task_spec, evidence)

        tier = decision["tier"]
        action = decision["action"] or "—"
        tier_icon = {"ok": "✓", "minor": "⚠", "major": "⚡"}.get(tier, "?")

        print(f"[Turn {i:02d}] {description}")
        print(f"         Challenge: {decision['challenge']:.3f}  "
              f"Outside: {'YES' if decision['outside_band'] else 'no '}  "
              f"DriftPct: {decision['drift_pct']:.2f}")
        print(f"         Tier: {tier_icon} {tier.upper():<7}  Action: {action}")
        if decision["frustration"]:
            print(f"         ** FRUSTRATION FLAG **")
        print(f"         Mastery:  "
              f"solve={state.mastery['solve_one_variable']:.3f}  "
              f"equiv={state.mastery['check_equivalence']:.3f}  "
              f"steps={state.mastery['show_work_steps']:.3f}  "
              f"verify={state.mastery['verify_solution']:.3f}")
        print(f"         Affect:   "
              f"S={state.affect.salience:.2f} "
              f"V={state.affect.valence:+.2f} "
              f"A={state.affect.arousal:.2f}  "
              f"Uncertainty={state.uncertainty:.2f}")
        print()

    print_separator("═")
    print("  Final state after 15 turns:")
    print(f"  Mastery:  solve={state.mastery['solve_one_variable']:.3f}  "
          f"equiv={state.mastery['check_equivalence']:.3f}  "
          f"steps={state.mastery['show_work_steps']:.3f}  "
          f"verify={state.mastery['verify_solution']:.3f}")
    print(f"  Affect:   S={state.affect.salience:.2f} "
          f"V={state.affect.valence:+.2f} "
          f"A={state.affect.arousal:.2f}")
    print(f"  ZPD window: outside_pct={state.recent_window.outside_pct:.2f}  "
          f"consecutive_outside={state.recent_window.consecutive_outside}")
    print_separator("═")


if __name__ == "__main__":
    run_demo()
