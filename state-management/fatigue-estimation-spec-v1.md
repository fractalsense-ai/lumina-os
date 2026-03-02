# Fatigue Estimation Specification — V1

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

Fatigue is a secondary signal in the Project Lumina state model. While ZPD drift is the primary indicator for scaffolding decisions, **cognitive fatigue** affects the reliability of performance data and the appropriate response strategy.

This document specifies how fatigue is estimated, what it affects, and what it does not affect.

---

## Design Constraints

1. **Fatigue must not be inferred from conversation content.** It is estimated from structural signals: response latency, error rate trends, hint frequency, and session length.
2. **Fatigue does not affect mastery scoring directly.** Mastery is scored per-task based on performance. Fatigue is a context signal, not a mastery modifier.
3. **Fatigue is an advisory signal only.** The Domain Authority may configure standing orders that respond to fatigue, but fatigue alone does not cause escalation.

---

## Fatigue Indicators

Fatigue is estimated from the following structural signals:

| Signal | Fatigue Interpretation |
|--------|----------------------|
| `response_latency_sec` increasing trend | Cognitive slowing |
| `hint_count` increasing per session | Declining self-sufficiency |
| `off_task_ratio` increasing | Attention drift |
| Session duration (turns) | Time-on-task load |
| `consecutive_incorrect` increasing after prior accuracy | Degrading from a competent baseline |

### Fatigue Score Formula

```
fatigue = 0.0

# Latency trend (rolling 5-turn average vs. session baseline)
if latency_trend > 1.5x_baseline:
    fatigue += 0.2
elif latency_trend > 1.25x_baseline:
    fatigue += 0.1

# Hint acceleration (hint rate in last 5 turns vs. first 5 turns)
if late_hint_rate > 2x_early_hint_rate:
    fatigue += 0.2

# Off-task drift
if off_task_ratio > 0.3:
    fatigue += 0.15

# Session length
if session_turns > 40:
    fatigue += 0.1
if session_turns > 60:
    fatigue += 0.1  # additional

# Degradation from baseline
if accuracy_last_5 < accuracy_first_5 - 0.3:
    fatigue += 0.2

fatigue = clamp(fatigue, 0.0, 1.0)
```

---

## Fatigue Thresholds

| Fatigue Level | Score | Interpretation | Advisory Action |
|--------------|-------|---------------|----------------|
| Low | 0.0 – 0.3 | Normal operating range | None |
| Moderate | 0.3 – 0.6 | Signs of cognitive load | Suggest a short break (via standing order if configured) |
| High | 0.6 – 0.8 | Significant fatigue | Standing order: reduce challenge; offer break |
| Critical | 0.8 – 1.0 | Session may not produce valid data | Standing order: recommend session close |

---

## Effect on Mastery Updates

Fatigue does **not** modify the mastery update formula directly. However:

- A Domain Authority may configure a `fatigue_context` flag in the domain pack that marks mastery updates during high-fatigue conditions as "fatigue-context" in the `OutcomeRecord`
- Mastery deltas during fatigue-context turns are still applied, but the `OutcomeRecord` notes the context
- The Domain Authority may review fatigue-context outcomes and override mastery deltas (via a `CommitmentRecord`) if they judge the performance to be unreliable

This preserves the principle that mastery assessment is based on task performance, while providing the Domain Authority with the context to exercise judgment.

---

## Effect on ZPD Band

Fatigue does **not** automatically change the ZPD band. However:

- High fatigue may cause apparent "downward drift" (tasks that were in-band become too challenging) — this can look like ZPD drift
- The ZPD monitor's drift detection operates on challenge vs. band, not on fatigue
- If fatigue-driven drift is suspected, the Domain Authority may update the ZPD band via a domain pack update

---

## Fatigue in the CTL

Fatigue score is not stored in the CTL as a separate field. It is captured via:
- `affect.arousal` (declining arousal correlates with fatigue)
- `evidence_summary.response_latency_sec` (in TraceEvents)
- Session-close `CommitmentRecord` may include a `fatigue_summary` in metadata

---

## Privacy

Fatigue estimation uses only structural signals — no behavioral inference from conversation content. Fatigue score is advisory and is not surfaced to the learner (telling a learner they appear "cognitively exhausted" is not pedagogically useful and may be harmful).

---

## Standing Order Integration

Domain Authorities may configure standing orders that respond to fatigue:

```yaml
standing_orders:
  - id: high_fatigue_response
    action: suggest_break
    trigger_condition: "fatigue_score >= 0.6"
    max_attempts: 1
    escalation_on_exhaust: false
    description: "Offer the student a break when fatigue is high"
```

If no fatigue-responsive standing order is configured, the fatigue score is computed but no automated action is taken.
