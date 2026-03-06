# Education Evaluation Tests

This document contains education-domain-specific domain-lib evaluation cases that are intentionally not part of root/core harness specs.

## Domain Lib Correctness (Education)

**TC-ZPD-001: Minor drift detection**
- Trigger: Inject 3 of 10 turns with `outside_pct` >= `minor_drift_threshold`
- Assert: Decision is `minor` (`zpd_scaffold`)
- Pass criterion: Correct tier

**TC-ZPD-002: Major drift detection**
- Trigger: Inject 5 of 10 turns with `outside_pct` >= `major_drift_threshold`
- Assert: Decision is `major` (`zpd_intervene_or_escalate`)
- Pass criterion: Correct tier

**TC-ZPD-003: No false drift in ZPD band**
- Trigger: Keep all challenge values within ZPD band for 10 turns
- Assert: No drift detected; decision is `ok`
- Pass criterion: Decision is `ok`

**TC-ZPD-004: Frustration estimation from evidence**
- Trigger: Inject evidence with `consecutive_incorrect: 3`, `hint_count: 3`, `frustration_marker_count: 2`
- Assert: `estimate_frustration_flag()` returns `True`
- Pass criterion: Correct flag

## References

- [`domain-lib/zpd-monitor-spec-v1.md`](domain-lib/zpd-monitor-spec-v1.md)
- [`reference-implementations/zpd-monitor-v0.2.py`](reference-implementations/zpd-monitor-v0.2.py)
- [`../../specs/evaluation-harness-v1.md`](../../specs/evaluation-harness-v1.md)
