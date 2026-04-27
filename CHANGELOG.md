# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project uses two version tracks:

- **Implementation** (`pyproject.toml`) — tracks the software. Currently pre-1.0.
- **Specification** (`standards/lumina-core-v1.md`) — tracks the formal spec. Currently 1.1.0.

They intentionally diverge: the specification leads, the implementation follows.

---

## [Unreleased] — Lumina Framework Repositioning + Signal Decomposition Framework (Phase H) + Affect Monitoring Pipeline (Phases F & G)

### Changed — Lumina Framework / Model-Pack Repositioning

- Repositioned the public project identity from **Lumina OS** toward **Lumina Neuro-Symbolic Systems Framework** / **Lumina Framework**.
- Renamed the repository pack directory from `domain-packs/` to `model-packs/` and updated path references across configs, docs, scripts, tests, web plugin discovery, examples, and manifest entries.
- Added `docs/7-concepts/lumina-framework-ontology.md`, defining Lumina as the engine/framework, model-packs as pluggable modeled systems (the “mods” layer), and modules as subsystem routines/workflows inside a modeled system.
- Updated README, docs index, model-pack directory README, and contributor guidance to use model-pack terminology while leaving deeper compatibility identifiers such as `domain_pack_id` for the follow-up identifier-migration slice.

### Added — Phase H: Signal Decomposition Framework

- **New top-level package `lumina.signals`** — domain-agnostic, signal-name-agnostic primitives extracted from the SVA-specific `affect_monitor.py`. Public API: `SignalSample`, `SignalBaseline`, `SignalDriftSignal`, `update_baseline`, `compute_drift`, `check_envelope_deviation`, `check_shape_deviation`, `resample_to_daily`, `compute_spectral_signature`, `update_spectral_history`, `check_spectral_drift`, `render_advisory_message`, `pull_active_advisory`, `upsert_spectral_advisory`. Consolidates baseline/spectral/advisory math into the framework so every domain monitors arbitrary scalars (soil pH, motor vibration, lab instruments, …) through one code path.
- **`signals` block in `domain-physics-schema-v1.json`** — domains declare each observed scalar with `label`, `units`, `range`, `record_path` (dotted path into a record body), optional `advisory_priority`, `advisory_ttl_seconds`, `bands`, and `message_overrides` (`"<band>,<direction>"` or `"<band>,*"` keys).
- **`standards/spectral-advisory-schema-v1.json`** — formal schema for `learning_state.spectral_advisories[*]` records (`advisory_id`, `signal`, `band`, `direction`, `z_score`, `message`, `created_utc`, `expires_utc`).
- **Generalised daemon task** — `rhythm_fft_analysis` in `src/lumina/daemon/tasks.py` now reads `domain_physics["signals"]` and iterates every declared signal on every actor, with no SVA hard-coding. Direction is normalised to the symbolic vocabulary (`positive` / `negative` / `neutral`) at the advisory boundary; `Proposal.detail.direction` retains the integer form for back-compat.
- **Generalised in-session consumer** — `journal_domain_step` advisory pull now delegates to `lumina.signals.pull_active_advisory`, which arbitrates across all signals (not just SVA axes) by `advisory_priority` → `band_priority` → recency.
- **Scope Y education delegation** — `model-packs/education/domain-lib/affect_monitor.py` is now a delegating shim over `lumina.signals`, and the education pack ships its own `signals` physics block declaring SVA axes with education-flavored `message_overrides`.
- **Agriculture POC** — `model-packs/agriculture/modules/operations-level-1/domain-physics.json` declares four sensor signals (`soil_pH`, `soil_moisture`, `air_temperature`, `motor_vibration`) with per-signal `message_overrides`. New `to_signal_samples(...)` adapter on `model-packs/agriculture/domain-lib/sensors/environmental_sensors.py` bridges `SensorReading` records to `SignalSample`. Proves the framework runs end-to-end on a non-affect domain with no framework changes.
- **Documentation**:
  - `docs/7-concepts/signal-decomposition-framework.md` — concept doc covering the instruments-vs-reactions principle, the `signals` block contract, the advisory schema, and the steps to onboard a new domain.
  - `docs/3-functions/signals.md` — public API reference for `lumina.signals` including the dual integer/symbolic direction vocabulary.
- **Tests** (75+ new, total 4389 passed):
  - `tests/test_signals_*.py` (61 tests) — unit coverage for the new package (state, baseline, spectral, advisories, templates).
  - `tests/test_signals_agriculture_poc.py` (10 tests) — end-to-end agriculture POC using real pack files; synthesises a 60-day pH slide, runs the daemon, asserts persisted advisory conforms to `spectral-advisory-schema-v1.json`.
  - `tests/test_daemon_rhythm_fft_generic.py` (4 tests) — daemon-level regression using a synthetic `lab_research` domain with arbitrary signal names declared inline (no real pack files), proving signal-name-agnosticism, deeply-nested `record_path` extraction, exact-vs-wildcard `message_overrides` resolution, and per-signal `advisory_ttl_seconds` honoring.

### Changed — Phase H

- **Daemon direction normalisation bug fix** — `rhythm_fft_analysis` was passing the raw integer direction (`+1 / -1 / 0`) into `render_advisory_message` and `upsert_spectral_advisory`, which expect the symbolic form. The daemon now normalises at the bridge point, while `Proposal.detail` still keeps the integer for the existing daemon-test contract.
- **Legacy `rhythm_fft.py`** and its colocated test removed — fully superseded by `lumina.signals.spectral` + `lumina.signals.baseline`.

---

## [Unreleased] — Affect Monitoring Pipeline (Phases F & G)

### Added

- **Phase F — Heartbeat Shape Layer** — per-axis (valence, arousal, salience) baseline tracking with rolling envelope-aware EMA, capturing both central tendency and short-term variability for the actor's affective rhythm.
- **Phase G — Chronic Spectral Layer** — daemon-side `rhythm_fft_analysis` task performs lightweight FFT over historical affect samples to detect sustained drift across three temporal bands (DC drift, circaseptan ~7-day, ultradian sub-daily). Findings are persisted as `Proposal` records on the actor profile.
- **Phase G.5 — Spectral Advisory Surface** — chronic findings now leave the daemon and flow into in-session decision context:
  - `_upsert_spectral_advisory` writes deduped `{advisory_id, axis, band, direction, z_score, message, created_utc, expires_utc}` records to `learning_state.spectral_advisories` with a 24-hour TTL.
  - `journal_session_start(profile, ...)` returns the highest-priority active advisory (priority order: valence > arousal > salience; dc_drift > circaseptan > ultradian) for surfacing on the first turn of a new session.
  - `journal_domain_step` performs sticky piggyback delivery: if `state["session_advisory_surfaced"]` is unset, the active advisory is attached to the current decision and the flag is set, preventing repeat surfacing within the same session.
  - Web journal store (`src/web/services/journalStore.ts`) gains an `advisories` IndexedDB object store (DB version bumped 1 → 2) with `setAdvisory`, `getAdvisory` (auto-prunes on expiry), and `clearAdvisory` helpers.
- **Documentation**:
  - `docs/7-concepts/affect-monitoring-pipeline.md` — three-layer architecture concept doc with EMS triage analogy and data-flow diagram.
  - `docs/1-commands/daemon-tasks.md` — registered idle-dispatch tasks reference.
  - `docs/3-functions/affect-monitor.md` — public API surface for the affect-monitor module across phases A–G.5.
- **Tests** (12 new, total 4313):
  - `tests/test_journal_session_start.py` (6 tests) — session-start advisory pull, expiry pruning, axis priority, sticky piggyback semantics.
  - `tests/test_daemon_rhythm_fft.py::TestSpectralAdvisoryPersistence` (3 tests) — proposal-driven advisory write, TTL = 24h, same-band replacement.
  - `tests/test_manifest_integrity.py` (2 tests) — real `docs/MANIFEST.yaml` parses (>100 artifacts) and `check_manifest` summary line is well-formed (regression guard for the regex bug fixed below).

### Changed

- `model-packs/education/controllers/journal_adapters.py` — added `profile_data`, `persistence`, `user_id`, `session_id` plumbing through `journal_domain_step`; advisory attached at all five tier return points (warmup, tier3, tier2, tier1, ok).
- `model-packs/education/controllers/freeform_adapters.py` — `freeform_domain_step` now forwards new advisory plumbing kwargs to `journal_domain_step`.
- `src/lumina/api/session.py` — `domain_lib_step_fn` lambda now uses `inspect.signature` to forward `profile`, `persistence`, `user_id`, and `session_id` only when the underlying step function accepts them, preserving compatibility with non-journal domain steps.
- `src/lumina/daemon/tasks.py` — `rhythm_fft_analysis` now persists spectral findings as advisories on `learning_state.spectral_advisories` in addition to writing `Proposal` records.

### Fixed

- **`manifest_integrity` regex bug** — `_PATH_LINE_RE` previously required exactly two leading spaces (`r"^\s{2}-\s+path:\s+(.+)"`), which silently failed against the real `docs/MANIFEST.yaml` whose list items are zero-indented (PyYAML default emit). The pattern now accepts 0–2 leading spaces (`r"^\s{0,2}-\s+path:\s+(.+)"`), restoring full-manifest verification (271 artifacts now check vs. ~0 before). Two real-manifest regression tests guard against future regressions.

### Notes

- **G.5.4 scope deviation**: only the IndexedDB advisory storage helpers shipped on the web side; a React `<AdvisoryBanner>` component and `chat.py` response-channel wiring for `decision.advisory` are deferred to a later phase, since the current `src/web` codebase has no journal session UI to anchor a banner against.

---

## [0.1.0] — 2026-04-16

### Added

- **D.S.A. Framework** — Domain, State, Actor structural schema with four decision tiers (ok/minor/major/escalate)
- **Prompt Packet Assembly (PPA)** — 9-layer prompt contract assembly engine with TCP/IP-style layering
- **Inspection Middleware** — three-stage deterministic boundary (NLP extraction → schema validation → invariant checking)
- **SLM Compute Tier** — three-role SLM layer (Librarian, Physics Interpreter, Command Translator) with graceful degradation
- **Novel Synthesis Tracking** — two-key verification gate (LLM flags + Domain Authority confirms)
- **Slash Commands** — deterministic command execution bypassing the LLM entirely, three tiers (user/domain/admin)
- **Domain Pack Architecture** — self-contained domain packs with seven-component anatomy (physics, tool-adapters, runtime-adapter, NLP pre-interpreter, domain-lib, group-libraries, world-sim)
- **NLP Semantic Router** — three-pass domain classifier (keyword → vector → spaCy similarity)
- **Edge Vectorization** — per-domain vector isolation with VectorStoreRegistry
- **Execution Route Compilation** — AOT compilation of domain-physics into flat O(1) lookup tables
- **Resource Monitor Daemon** — load-based opportunistic task scheduling with cooperative preemption
- **Document Ingestion Pipeline** — SLM-driven content extraction and domain-physics generation
- **System Log** — append-only audit ledger with micro-router (DEBUG → rolling archive, AUDIT → immutable ledger)
- **Fractal Governance** — macro/meso/micro authority hierarchy with System Log accountability
- **Domain Role Hierarchy** — domain-scoped RBAC role tiers beneath Domain Authority ceiling
- **JWT Authentication** — dual-secret architecture (admin/user tier separation) with domain role claims
- **Persistence Layer** — SQLite, filesystem, and null adapters with key-based profile support
- **Three domain packs** — Education (algebra + world-sim + MUD builder), Agriculture (sensor ops + group libraries), System (SLM-only routing)
- **Web UI** — Vite + React reference frontend with PluginRegistry for domain-specific UI contributions
- **Test suite** — 3690+ pytest tests covering orchestrator, middleware, persistence, API, and domain packs
- **Documentation** — UNIX man-page convention (sections 1–8) with SHA-256 integrity tracking via MANIFEST.yaml
