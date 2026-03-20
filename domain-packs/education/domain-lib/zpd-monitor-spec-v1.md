# ZPD Monitor Specification — V1

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

The **ZPD Monitor** is the core state-management component of the Project Lumina Action layer. It maintains the compressed learner state, detects Zone of Proximal Development drift, and produces a decision tier for each turn.

The reference implementation is [`../reference-implementations/zpd-monitor-v0.2.py`](../reference-implementations/zpd-monitor-v0.2.py).

---

## Inputs and Outputs

### Per-Turn Inputs

```python
state: LearningState     # current compressed state
task_spec: dict          # current task specification from domain pack
evidence: dict           # structured evidence summary from this turn
params: dict | None      # optional override parameters
```

### Per-Turn Output

```python
(updated_state: LearningState, decision: dict)
```

Where decision contains:

```python
{
    "tier": "ok" | "minor" | "major",
    "action": None | "zpd_scaffold" | "zpd_intervene_or_escalate",
    "should_escalate": bool,  # True on major tier; engine checks this field
    "frustration": bool,
    "challenge": float,
    "outside_band": bool,
    "drift_pct": float,
    "reason": str
}
```

---

## Core Data Structures

```python
@dataclass
class AffectState:
    salience: float = 0.5    # 0..1
    valence: float = 0.0     # -1..1
    arousal: float = 0.5     # 0..1

@dataclass
class RecentWindow:
    window_turns: int = 10
    attempts: int = 0
    consecutive_incorrect: int = 0
    hint_count: int = 0
    outside_pct: float = 0.0
    consecutive_outside: int = 0
    outside_flags: List[bool] = field(default_factory=list)

@dataclass
class LearningState:
    affect: AffectState
    mastery: Dict[str, float]
    challenge_band: Dict[str, float]   # {"min_challenge": float, "max_challenge": float}
    recent_window: RecentWindow
    challenge: float = 0.5
    uncertainty: float = 0.5
```

---

## Core Functions

### `zpd_monitor_step`

The main entry point. Processes one turn and returns updated state and decision.

```python
def zpd_monitor_step(
    state: LearningState,
    task_spec: dict,
    evidence: dict,
    params: dict | None = None
) -> tuple[LearningState, dict]:
    params = params or DEFAULT_PARAMS

    # 1. Update mastery
    new_mastery = update_mastery(state.mastery, task_spec, evidence)

    # 2. Estimate challenge
    new_challenge = estimate_challenge(task_spec, new_mastery, state.uncertainty)

    # 3. Update affect
    new_affect = update_affect(state.affect, evidence)

    # 4. Estimate uncertainty
    new_uncertainty = estimate_uncertainty(state.uncertainty, evidence)

    # 5. Update ZPD window
    outside_band = (
        new_challenge < state.challenge_band["min_challenge"]
        or new_challenge > state.challenge_band["max_challenge"]
    )
    new_window = update_zpd_window(state.recent_window, outside_band)

    # 6. Detect drift
    frustration = estimate_frustration_flag(new_affect, new_window, evidence)
    decision = detect_drift(new_window, frustration, params)
    decision["challenge"] = new_challenge
    decision["outside_band"] = outside_band

    # 7. Assemble updated state
    new_state = LearningState(
        affect=new_affect,
        mastery=new_mastery,
        challenge_band=state.challenge_band,
        recent_window=new_window,
        challenge=new_challenge,
        uncertainty=new_uncertainty
    )

    return new_state, decision
```

### `detect_drift`

Converts window state into a decision tier:

```python
def detect_drift(window: RecentWindow, frustration: bool, params: dict) -> dict:
    if (window.outside_pct >= params["major_drift_threshold"]
            or window.consecutive_outside >= params["persistence_required"]
            or frustration):
        return {
            "tier": "major",
            "action": "zpd_intervene_or_escalate",
            "should_escalate": True,
            "frustration": frustration,
            "drift_pct": window.outside_pct,
            "reason": "major_zpd_drift_or_frustration"
        }
    elif window.outside_pct >= params["minor_drift_threshold"]:
        return {
            "tier": "minor",
            "action": "zpd_scaffold",
            "frustration": frustration,
            "drift_pct": window.outside_pct,
            "reason": "minor_zpd_drift"
        }
    else:
        return {
            "tier": "ok",
            "action": None,
            "frustration": frustration,
            "drift_pct": window.outside_pct,
            "reason": "within_zpd"
        }
```

---

## Decision Tiers

| Tier | Condition | Orchestrator Action |
|------|-----------|-------------------|
| `ok` | Within ZPD, no frustration | Continue normally |
| `minor` | `outside_pct >= minor_drift_threshold` | Apply `zpd_scaffold` standing order |
| `major` | `outside_pct >= major_drift_threshold` OR `consecutive_outside >= persistence` OR frustration | Apply `zpd_intervene_or_escalate` |

### Standing Order Responses

**`zpd_scaffold`** (minor drift):
- Reduce challenge level of next task
- Offer an optional hint
- Increase scaffolding in explanation

**`zpd_intervene_or_escalate`** (major drift):
- Pause current task
- Issue one probe (the single permitted probe per drift event)
- If probe response does not improve state: escalate

---

## Default Parameters

```python
DEFAULT_PARAMS = {
    "minor_drift_threshold": 0.3,
    "major_drift_threshold": 0.5,
    "persistence_required": 3,
    "window_turns": 10,
    "latency_threshold_sec": 60.0,
    "mastery_correct_no_hint": 0.10,
    "mastery_correct_hint": 0.03,
    "mastery_partial_no_hint": 0.02,
    "mastery_partial_hint": 0.01,
    "mastery_incorrect": -0.05,
    "mastery_repeated_error": -0.08,
}
```

---

## ZPD Band Updates

The ZPD band itself is updated by the Domain Authority, not by the ZPD monitor. The monitor operates within the band set by the domain pack. The band may be updated by the Domain Authority via a new domain pack version or an explicit standing order.

---

## Integration with System Log

After each `zpd_monitor_step`:
1. Compute the SHA-256 hash of the updated state (canonical JSON)
2. Append a `TraceEvent` to the System Logs with `state_snapshot_hash` and `decision`
3. The full state is not written to the System Logs — only the hash

---

## References

- [`compressed-state-estimators.md`](compressed-state-estimators.md) — detailed estimator formulas
- [`../reference-implementations/zpd-monitor-v0.2.py`](../reference-implementations/zpd-monitor-v0.2.py) — Python implementation
- [`../reference-implementations/zpd-monitor-demo.py`](../reference-implementations/zpd-monitor-demo.py) — worked demo
- [`../schemas/compressed-state-schema-v1.json`](../schemas/compressed-state-schema-v1.json) — state schema
