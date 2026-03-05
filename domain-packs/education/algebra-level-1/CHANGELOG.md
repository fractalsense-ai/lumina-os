# Algebra Level 1 Domain Pack — CHANGELOG

All notable changes to this domain pack will be documented here.

---

## v0.4.0 — 2026-03-05

### Changed
- Renamed `learning_state.zpd_band` → `learning_state.challenge_band` in student profiles
  to align with the updated universal `compressed-state-schema-v1.json` and
  `student-profile-schema-v1.json`, which now use the domain-neutral field name
  `challenge_band`. In education contexts this field corresponds to the Zone of Proximal
  Development (ZPD). No parameter values are changed.

---

## v0.3.0 — 2026-03-05

### Changed
- Renamed top-level `zpd_config` to `subsystem_configs.zpd_monitor` to align with the
  updated universal domain-physics-schema-v1 which now uses a generic `subsystem_configs`
  map instead of the education-specific `zpd_config` field. All parameter values are
  unchanged.

---

## v0.2.0 — 2026-03-02

### Added
- ZPD configuration: `min_challenge: 0.3`, `max_challenge: 0.7`, `drift_window_turns: 10`
- `zpd_drift_minor` warning invariant — triggers `zpd_scaffold` standing order
- `zpd_drift_major` warning invariant — triggers `zpd_intervene_or_escalate` standing order
- `zpd_scaffold` and `zpd_intervene_or_escalate` standing orders
- `zpd_summary` evidence summary type
- Persistence requirement: `persistence_required: 3`

### Changed
- `show_work_minimum` max_attempts increased from 2 to 3
- Escalation SLA reduced to 30 minutes (from unspecified)
- Added `major_zpd_drift_unresolved` escalation trigger

### Fixed
- `standard_method_preferred` now correctly references `request_method_justification` standing order

---

## v0.1.0 — 2026-02-15

### Added
- Initial domain pack: Algebra Level 1 for middle school
- Core invariants: `equivalence_preserved`, `no_illegal_operations`, `solution_verifies`
- Warning invariants: `standard_method_preferred`, `show_work_minimum`
- Standing orders: `request_more_steps`, `request_method_justification`
- Escalation trigger: `critical_invariant_unresolvable`
- Artifacts: `linear_equations_basic`
- Tool adapters: `calculator-adapter-v1`, `substitution-checker-adapter-v1`
- Evidence summary types: `step_diff_summary`, `illegal_ops_summary`, `verification_summary`, `method_summary`, `step_count_summary`, `affect_summary`
