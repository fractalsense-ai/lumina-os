# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project uses two version tracks:

- **Implementation** (`pyproject.toml`) — tracks the software. Currently pre-1.0.
- **Specification** (`standards/lumina-core-v1.md`) — tracks the formal spec. Currently 1.1.0.

They intentionally diverge: the specification leads, the implementation follows.

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

- `domain-packs/education/controllers/journal_adapters.py` — added `profile_data`, `persistence`, `user_id`, `session_id` plumbing through `journal_domain_step`; advisory attached at all five tier return points (warmup, tier3, tier2, tier1, ok).
- `domain-packs/education/controllers/freeform_adapters.py` — `freeform_domain_step` now forwards new advisory plumbing kwargs to `journal_domain_step`.
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
