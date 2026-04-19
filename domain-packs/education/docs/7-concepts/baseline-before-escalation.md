---
version: 1.0.0
last_updated: 2026-04-19
---

# Baseline-Before-Escalation — Education Domain Examples

For the framework-level gate design, see
[`docs/7-concepts/baseline-before-escalation.md`](../../../../docs/7-concepts/baseline-before-escalation.md).

---

## ZPD drift window (structured modules)

The ZPD monitor's drift detection uses a rolling window of
`drift_window_turns` (default 10) attempts.  Until the window is full,
drift percentages are based on incomplete data.

`learning_adapters.domain_step()` compares `window_turns_filled` (from
the ZPD decision dict) against `drift_window_turns` and sets
`escalation_eligible: false` while `filled < window_size`.

## Vocabulary growth baseline (freeform modules)

The vocabulary growth monitor collects `baseline_sessions` (default 3)
complexity samples before locking the baseline.  During this period
`measurement_valid` is `false` and growth deltas are undefined.

`freeform_adapters.freeform_domain_step()` checks
`vocabulary_tracking.baseline_sessions_remaining > 0` and sets
`escalation_eligible: false` until the baseline locks.

## See also

- [`ZPD theory and drift monitoring`](../README.md) — education concepts index
- [`vocabulary-growth-monitor(3)`](../3-functions/vocabulary-growth-monitor.md) — vocabulary monitor specification
