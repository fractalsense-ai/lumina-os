---
version: 1.0.0
last_updated: 2026-04-05
---

# Learning Profile

The education domain uses a **3-layer hierarchical profile** system:

| Layer | File | Purpose |
|---|---|---|
| Base | `domain-packs/system/cfg/base-entity-profile.yaml` | Universal fields (entity_id, display_name) |
| Domain | `domain-packs/education/cfg/domain-profile-extension.yaml` | Consent, session history, teacher notes |
| Role | `domain-packs/education/profiles/student.yaml` | Learning state, mastery, preferences |

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

### Domain Extension Fields
- `consent` — magic-circle acceptance state
- `session_history` — aggregate session stats
- `teacher_notes: []` — append-only timestamped notes from teachers

## Teacher Commands

- **`update_student_preferences`** — update learning preferences and add a teacher note
- **`assign_student`** / **`remove_student`** — manage teacher roster
- **`assign_module`** / **`remove_module`** — manage module enrolment
