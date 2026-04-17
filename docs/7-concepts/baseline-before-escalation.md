---
version: 1.0.0
last_updated: 2026-06-14
---

# baseline-before-escalation(7) — Suppressing premature metric escalation

## Name

baseline-before-escalation — framework gate that prevents delta-based
escalation events from firing until the originating subsystem has primed
its baseline.

## Synopsis

A domain-lib step function sets `escalation_eligible: false` in its
decision dict while its subsystem baseline is still forming.  The
framework's `ActorResolver.resolve()` reads this field and suppresses
metric-driven escalation without affecting safety/invariant escalation.

## Description

Many Lumina subsystems track *deltas* — change relative to an
established baseline.  Examples include the ZPD drift window (education),
the SVA vocabulary growth monitor (education), and future analog
subsystems in agriculture (soil sensor drift) or other domains.

Deltas computed before the baseline stabilises are meaningless noise.
If an escalation fires during this calibration period it wastes human
attention and erodes trust in the system.

### Two-layer design

| Layer | Where | Responsibility |
|-------|-------|----------------|
| **Domain signal** | Domain-lib step function | Computes `escalation_eligible` based on subsystem-specific readiness criteria |
| **Framework gate** | `ActorResolver.resolve()` | Reads `escalation_eligible`; suppresses `should_escalate` when `false` |

### What is NOT gated

Safety/invariant escalation (standing-order exhaustion) is resolved
**before** the domain-lib decision is inspected and is never suppressed
by this gate.  Only the `domain_lib_escalation_event` path is affected.

### Default behaviour

If `escalation_eligible` is absent from the decision dict, the framework
treats it as `true` (backward-compatible — existing domain packs that
do not set the field are unaffected).

## Education domain examples

### ZPD drift window (structured modules)

The ZPD monitor's drift detection uses a rolling window of
`drift_window_turns` (default 10) attempts.  Until the window is full,
drift percentages are based on incomplete data.

`learning_adapters.domain_step()` compares `window_turns_filled` (from
the ZPD decision dict) against `drift_window_turns` and sets
`escalation_eligible: false` while `filled < window_size`.

### Vocabulary growth baseline (freeform modules)

The vocabulary growth monitor collects `baseline_sessions` (default 3)
complexity samples before locking the baseline.  During this period
`measurement_valid` is `false` and growth deltas are undefined.

`freeform_adapters.freeform_domain_step()` checks
`vocabulary_tracking.baseline_sessions_remaining > 0` and sets
`escalation_eligible: false` until the baseline locks.

## Adding baseline gating to a new domain pack

1. Identify the subsystem's readiness criterion (window fill count,
   sample count, warm-up period, etc.).
2. Expose a readiness indicator in the subsystem's decision dict.
3. In the domain adapter's step function, set
   `decision["escalation_eligible"] = False` while readiness is unmet.
4. The framework gate handles the rest — no changes to
   `ActorResolver` are needed.

## See also

- `escalation-auto-freeze(7)` — what happens when escalation *does* fire
- `dsa-framework(7)` — Actor resolution pipeline
- `domain-adapter-pattern(7)` — step function conventions
