# Compressed State Estimators — Project Lumina

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

This document specifies the deterministic heuristics used to maintain the compressed learner state. All estimators are deterministic — they use no ML models. They take structured evidence as input and produce updated state values.

The reference implementation is in [`../reference-implementations/zpd-monitor-v0.2.py`](../reference-implementations/zpd-monitor-v0.2.py).

---

## State Variables

| Variable | Type | Range | Description |
|----------|------|-------|-------------|
| `salience` | float | 0..1 | Engagement/focus level |
| `valence` | float | -1..1 | Emotional tone (negative to positive) |
| `arousal` | float | 0..1 | Activation level (flat to frantic) |
| `mastery[skill]` | float | 0..1 | Per-skill mastery estimate |
| `challenge` | float | 0..1 | Estimated task challenge level |
| `uncertainty` | float | 0..1 | Orchestrator uncertainty about state |
| `zpd_band.min` | float | 0..1 | Lower ZPD bound |
| `zpd_band.max` | float | 0..1 | Upper ZPD bound |
| `window.outside_pct` | float | 0..1 | Fraction of window turns outside ZPD |
| `window.consecutive_outside` | int | ≥0 | Consecutive turns outside ZPD |
| `window.consecutive_incorrect` | int | ≥0 | Consecutive incorrect responses |
| `window.hint_count` | int | ≥0 | Hints used in current window |

---

## Evidence Input Structure

All estimators receive structured evidence — never raw text:

```python
evidence = {
    "correctness": "correct" | "incorrect" | "partial",
    "hint_used": bool,
    "response_latency_sec": float,  # seconds to respond
    "frustration_marker_count": int,  # signals from domain invariants
    "repeated_error": bool,           # same error as previous attempt
    "off_task_ratio": float           # 0..1, from domain tool adapters
}
```

Evidence is produced by tool adapters (e.g., the substitution checker, step validator) and the domain's evidence summary pipeline — not by reading conversation tone.

---

## Affect Estimator

### Salience

Salience decreases with disengagement signals and increases with active engagement:

```
Δsalience = 0
if off_task_ratio > 0.5: Δsalience -= 0.1
if response_latency_sec > latency_threshold: Δsalience -= 0.05
if correctness == "correct" and not hint_used: Δsalience += 0.05
salience = clamp(prev_salience + Δsalience, 0, 1)
```

### Valence

Valence reflects emotional tone — success increases it, frustration decreases it:

```
Δvalence = 0
if correctness == "correct" and not hint_used: Δvalence += 0.1
if correctness == "correct" and hint_used: Δvalence += 0.03
if correctness == "incorrect": Δvalence -= 0.08
if correctness == "partial": Δvalence -= 0.02
if frustration_marker_count >= 2: Δvalence -= 0.1
valence = clamp(prev_valence + Δvalence, -1, 1)
```

### Arousal

Arousal reflects activation — high latency is low arousal; frustration is high arousal:

```
Δarousal = 0
if response_latency_sec < 3.0: Δarousal += 0.05  # fast response = higher arousal
if response_latency_sec > 30.0: Δarousal -= 0.1  # very slow = lower arousal
if frustration_marker_count >= 2: Δarousal += 0.15  # frustration spikes arousal
arousal = clamp(prev_arousal + Δarousal, 0, 1)
```

---

## Frustration Flag Estimator

A binary flag used by the ZPD monitor to detect acute frustration:

```
frustration = (
    consecutive_incorrect >= 3
    OR hint_count >= 3
    OR frustration_marker_count >= 2
    OR (repeated_error AND consecutive_incorrect >= 2)
)
```

---

## Challenge Estimator

Challenge is estimated from the task specification and current mastery:

```
mean_mastery = mean(student_mastery[s] for s in task.skills_required)
base_challenge = task.nominal_difficulty  # 0..1, set in domain pack
mastery_adjustment = (0.5 - mean_mastery) * 0.4
uncertainty_adjustment = uncertainty * 0.1
challenge = clamp(base_challenge + mastery_adjustment + uncertainty_adjustment, 0, 1)
```

---

## Uncertainty Estimator

Uncertainty decays when evidence is consistent and grows when evidence is contradictory:

```
if correctness == "correct" and not hint_used:
    Δuncertainty = -0.1
elif correctness == "incorrect" and repeated_error:
    Δuncertainty = +0.05
elif correctness == "partial":
    Δuncertainty = +0.02
else:
    Δuncertainty = -0.05
uncertainty = clamp(prev_uncertainty + Δuncertainty, 0, 1)
```

---

## Mastery Update Rules

Per-skill mastery is updated based on evidence:

| Condition | Δ mastery |
|-----------|-----------|
| Correct, no hint | +0.10 |
| Correct, hint used | +0.03 |
| Partial, no hint | +0.02 |
| Partial, hint used | +0.01 |
| Incorrect, first time | -0.05 |
| Incorrect, repeated error | -0.08 |

Mastery is clamped to [0, 1]. Skills not exercised in the current task are unchanged.

---

## ZPD Window Update

The rolling window tracks per-turn outside-ZPD flags:

```
outside_band = challenge < zpd_band.min OR challenge > zpd_band.max
outside_flags = ([outside_band] + prev_flags)[:window_turns]
outside_pct = sum(outside_flags) / window_turns
consecutive_outside = (
    prev_consecutive_outside + 1 if outside_band
    else 0
)
```

---

## ZPD Drift Detection

| Condition | Tier | Action |
|-----------|------|--------|
| `outside_pct < minor_threshold` | `ok` | None |
| `outside_pct >= minor_threshold` | `minor` | Apply `zpd_scaffold` standing order |
| `outside_pct >= major_threshold` OR `consecutive_outside >= persistence_required` | `major` | Apply `zpd_intervene_or_escalate` |

Drift detection runs after each window update.

---

## Parameter Defaults

If a domain pack does not specify override values:

| Parameter | Default |
|-----------|---------|
| `window_turns` | 10 |
| `minor_drift_threshold` | 0.3 |
| `major_drift_threshold` | 0.5 |
| `persistence_required` | 3 |
| `latency_threshold_sec` | 60.0 |

---

## Implementation Note

All estimators use simple arithmetic — no ML. The intent is that the Domain Authority can read and understand the update rules, predict the system's behavior, and tune thresholds accordingly. Opacity is a governance risk.
