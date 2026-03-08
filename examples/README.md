# Examples — Project Lumina

This directory contains worked examples of Project Lumina interaction loops.

---

## Contents

| File | Description |
|------|-------------|
| `causal-learning-trace-example.json` | CTL records from a real (simulated) 5-turn algebra session |
| `escalation-example-packet.yaml` | A complete escalation packet for a major ZPD drift event |

---

## Walkthrough: One Full Interaction Loop

This walkthrough traces a single turn of an algebra session with student Alice.

### Setup

- **Domain:** Algebra Level 1 v0.4.0
- **Student:** Alice (pseudonymous ID: `a3f8c2e1b4d7f9a0c5e2b8d1a6f3c7e4`)
- **Session:** turn 6 (mid-session)
- **Current state:** Alice has been doing well (mastery ~0.65) but is now attempting a harder problem

### Turn 6 — Step by Step

**1. Load and verify domain pack**

The orchestrator loads `domain-physics.json` and verifies its SHA-256 hash against the `CommitmentRecord` in the CTL. If the hash doesn't match, the session is frozen.

**2. Task presentation**

Alice is presented with: `Solve for x: 3x + 7 = 22`  
Task nominal_difficulty: 0.65  
The domain is using a "space mission" world simulation theme because Alice likes space, so the task is framed as: *"The fuel calculation for today's mission requires solving: 3x + 7 = 22. Find x."*

**3. Alice responds**

Alice writes: `x = 5`

Her response is one step with no work shown.

**4. Tool adapters run**

- **substitution-checker**: Substitutes x=5 into 3x+7=22 → LHS=22, RHS=22 → ✓
- **step-counter**: Only 1 step shown → violates `show_work_minimum` (≥3 required)
- **method-recognizer**: Direct substitution without showing work → `method_recognized: false`

**5. Evidence summary assembled**

```json
{
  "correctness": "correct",
  "hint_used": false,
  "response_latency_sec": 8.0,
  "frustration_marker_count": 0,
  "repeated_error": false,
  "off_task_ratio": 0.0
}
```

**6. ZPD monitor step runs**

The monitor processes the evidence. The answer is correct, so mastery increases. But challenge (0.65) is within Alice's ZPD band [0.3, 0.7], so no ZPD drift.

**7. Invariant checks**

- `equivalence_preserved`: N/A (no step-by-step shown)
- `solution_verifies`: PASS (substitution check passed)
- `show_work_minimum`: FAIL — only 1 step shown (requires 3)

**8. Standing order applied**

`show_work_minimum` fired → standing order `request_more_steps` (attempt 1/3)

Orchestrator response: *"Great — x=5 is correct! But I need to see your work. Can you show me at least 3 steps? Start from 3x + 7 = 22 and show each transformation."*

**9. CTL TraceEvent written**

```json
{
  "record_type": "TraceEvent",
  "event_type": "standing_order_applied",
  "standing_order_id": "request_more_steps",
  "standing_order_attempt": 1,
  "decision": "show_work_minimum_violated_correct_answer",
  "evidence_summary": {
    "correctness": "correct",
    "hint_used": false,
    "response_latency_sec": 8.0,
    "frustration_marker_count": 0,
    "repeated_error": false,
    "off_task_ratio": 0.0
  }
}
```

**10. Alice responds again**

Alice shows her work:
```
3x + 7 = 22
3x = 22 - 7
3x = 15
x = 5
```

**11. Tool adapters run again**

- step-counter: 4 steps → PASS
- equivalence-checker: Each step preserves equivalence → PASS
- substitution-checker: x=5 verifies → PASS

**12. All invariants pass**

No standing orders needed. CTL `TraceEvent` written with `decision: "all_invariants_pass"`.

**13. Mastery update**

`solve_one_variable` and `show_work_steps` mastery both increase (correct, no hint, showed work).

**14. Session continues**

Alice earned a `+0.10` mastery boost on `solve_one_variable`. The orchestrator prepares the next task.

---

## Key Points

1. **The answer being correct doesn't mean all invariants pass.** `show_work_minimum` fired even though the answer was right.
2. **Standing orders have limited attempts.** If Alice had refused to show her work 3 times, the orchestrator would have escalated to the teacher.
3. **The CTL only records structured telemetry.** Neither Alice's problem response nor the AI's reply is stored. Only hashes and decision summaries are written.
4. **World simulation is transparent.** The "space mission" framing changes how the problem is presented but not what is checked.
5. **Mastery increases correctly.** Since Alice was correct and showed her work without hints, she gets the full `+0.10` mastery boost.
