---
version: 1.1.0
last_updated: 2026-06-15
---

# Learning Profile

The education domain uses a **3-layer hierarchical profile** system:

| Layer | File | Purpose |
|---|---|---|
| Base | `model-packs/system/cfg/base-entity-profile.yaml` | Universal fields (entity_id, display_name) |
| Domain | `model-packs/education/cfg/domain-profile-extension.yaml` | Consent, session history, teacher notes |
| Role | `model-packs/education/profiles/student.yaml` | Learning state, mastery, preferences |

## Student Profile Fields (v1.1.0)

### Preferences
- `interests: []` — student interests (teacher-editable)
- `dislikes: []` — student dislikes (teacher-editable)
- `preferred_explanation_style: step_by_step` — hint delivery style
- `simulator_preference: rpg` — MUD/RPG world-sim preference

### Staff Assignment
- `assigned_ta_ids: []` — assigned teaching assistants
- `assigned_guardian_ids: []` — assigned guardians/parents

### Per-Module Mastery
- `module_mastery: {}` — keyed by module ID, populated as student enters modules

### Learning State
- `affect` — salience, valence, arousal
- `mastery` — per-invariant mastery scores
- `challenge_band` — min/max challenge range
- `recent_window` — sliding window stats
- `fluency` — tier progression tracking
- `vocabulary_tracking` — vocabulary growth measurement (see below)

### Domain Extension Fields
- `consent` — magic-circle acceptance state
- `session_history` — aggregate session stats
- `teacher_notes: []` — append-only timestamped notes from teachers

## Teacher Commands

- **`update_user_preferences`** — update user preferences (self-service or supervisor on behalf)
- **`assign_student`** / **`remove_student`** — manage teacher roster
- **`assign_module`** / **`remove_module`** — manage module enrolment

## Vocabulary Tracking (v0.1.0)

The `vocabulary_tracking` block within `learning_state` tracks vocabulary complexity growth
across sessions. Scores are computed client-side by `vocabularyAnalyzer.ts` and posted via
the domain-declared `POST /api/user/{user_id}/vocabulary-metric` route.

| Field | Type | Description |
|-------|------|-------------|
| `baseline_complexity` | `float \| None` | Locked baseline (average of first N sessions) |
| `current_complexity` | `float \| None` | Most recent composite score (0..1) |
| `growth_delta` | `float` | Growth above baseline (always ≥ 0) |
| `domain_vocabulary` | `dict` | Per-module term acquisition: `{module_id: {terms_acquired, complexity_delta}}` |
| `measurement_window_turns` | `int` | Client-side analysis window size |
| `baseline_sessions_remaining` | `int` | Sessions until baseline locks |
| `baseline_samples` | `list[float]` | Collected baseline scores |
| `last_measured_utc` | `str \| None` | ISO 8601 timestamp of last measurement |
| `session_history` | `list[dict]` | Rolling `{complexity, delta, measured_utc}` entries (max 50) |

The baseline locks after `baseline_lock_sessions` (default 3) measurements, providing a
stable reference point. Growth delta is always non-negative — no punishment for temporary
regression.

For the full monitor specification, see
[`vocabulary-growth-monitor(3)`](../../model-packs/education/docs/3-functions/vocabulary-growth-monitor.md).
For the dashboard panel, see the `vocabulary_growth` entry in the education domain's
`ui_manifest.panels` in `cfg/runtime-config.yaml`.
