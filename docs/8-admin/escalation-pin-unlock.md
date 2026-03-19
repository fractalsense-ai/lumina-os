# Escalation PIN Unlock

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-19

---

## Overview

Session freeze/unlock is an education-domain safety mechanism that allows a teacher (or Domain Authority) to temporarily pause a student's active session while a pending escalation is under review. The session is "frozen" — the student cannot continue interacting with the tutor — until a teacher-issued one-time PIN is entered, either in the chat interface or via the dedicated unlock endpoint.

This mechanism is triggered during escalation resolution: when a teacher resolves an escalation with `generate_pin: true`, the system simultaneously records the resolution, generates a 6-digit OTP, freezes the session, and returns the PIN to the teacher. The teacher delivers the PIN to the student out-of-band (verbally, on paper, or via a classroom communication channel), and the student enters it to resume.

---

## Smart Escalation Routing

When the orchestrator writes an escalation record, it automatically populates two routing fields from the student's profile:

| Field | Source | Purpose |
|-------|--------|---------|
| `escalation_target_id` | `student_profile.assigned_teacher_id` | Routes the escalation directly to the assigned teacher |
| `assigned_room_id` | `student_profile.assigned_room_id` | Carries classroom context for multi-room deployments |

These fields allow dashboards, notification systems, and governance tooling to deliver the escalation to the correct teacher without manual routing. When `assigned_teacher_id` is absent from the profile, `escalation_target_id` is `null` and the escalation falls through to general domain-authority review.

---

## Student Profile Assignment Fields

Assignment fields are stored in the student profile document (`domain-packs/education/schemas/student-profile-schema-v1.json`):

| Field | Type | Description |
|-------|------|-------------|
| `assigned_teacher_id` | `string` | Actor ID of the teacher responsible for this student. Matched to `escalation_target_id` during escalation routing. |
| `assigned_room_id` | `string` | Classroom or cohort identifier. Carried into escalation records for context. |
| `intervention_history` | `array` | Ordered list of `intervention_record` entries written at escalation resolve time. |

### `intervention_record` shape

```json
{
  "escalation_id": "esc-abc123",
  "teacher_id": "teacher_pseudonymous_id",
  "notes": "Student struggled with distributive property steps 2–3. Suggested worked example.",
  "recorded_utc": "2026-03-19T14:22:00+00:00",
  "generated_proposal": false
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `escalation_id` | yes | ID of the escalation that triggered the intervention |
| `teacher_id` | yes | `sub` claim of the JWT used to resolve the escalation |
| `notes` | yes | Free-text notes from the resolution request |
| `recorded_utc` | yes | ISO 8601 UTC timestamp of when the record was written |
| `generated_proposal` | yes | `true` when `generate_proposal` was set in the resolve request — marks this entry for night-cycle proposal generation |

---

## End-to-End Workflow

```
1. Student session → escalation trigger
   ─ PPA orchestrator writes escalation record
   ─ escalation_target_id ← student_profile.assigned_teacher_id
   ─ assigned_room_id ← student_profile.assigned_room_id

2. Teacher reviews escalation
   ─ GET /api/escalations?status=open

3. Teacher resolves with PIN generation
   ─ POST /api/escalations/{escalation_id}/resolve
     {"decision": "approve", "reasoning": "...", "generate_pin": true,
      "intervention_notes": "...", "generate_proposal": false}
   ← {"record_id": "...", "escalation_id": "...",
       "decision": "approve", "unlock_pin": "042817"}
   ─ Session container: frozen = True
   ─ PIN stored in memory (TTL: LUMINA_UNLOCK_PIN_TTL_SECONDS, default 900 s)
   ─ Intervention notes appended to student profile intervention_history

4. Teacher delivers PIN to student out-of-band
   ─ Verbally, on paper, or via classroom system

5a. Student enters PIN in chat
    ─ POST /api/chat {"session_id": "...", "message": "042817", ...}
    ← {"action": "session_unlocked", "escalated": false,
        "response": "Session unlocked. You may continue."}
    ─ Session container: frozen = False
    ─ PIN consumed (single-use)

5b. Teacher unlocks via API (alternative to 5a)
    ─ POST /api/sessions/{session_id}/unlock {"pin": "042817"}
    ← {"session_id": "...", "unlocked": true}
    ─ Session container: frozen = False
    ─ PIN consumed (single-use)

6. Student continues session normally
```

---

## Frozen Session Behaviour

While `SessionContainer.frozen` is `True`, the chat pipeline is short-circuited before any D.S.A. processing:

| Input | Response `action` | Session state |
|-------|--------------------|---------------|
| Any non-PIN message | `session_frozen` | Remains frozen |
| 6-digit string that does not match the stored PIN | `session_frozen` | Remains frozen |
| Correct 6-digit PIN | `session_unlocked` | Unfrozen; PIN consumed |
| No PIN stored (expired or never generated) | `session_frozen` | Remains frozen |

HTTP status is `200` in all cases. The `escalated` flag mirrors whether the session is still frozen (`true` = frozen, `false` = unlocked).

---

## PIN Behaviour

| Property | Value |
|----------|-------|
| Format | 6-digit zero-padded decimal string (`000000`–`999999`) |
| Single-use | Consumed on first correct validation; subsequent calls return `session_frozen` |
| TTL | `LUMINA_UNLOCK_PIN_TTL_SECONDS` environment variable (default `900` seconds / 15 minutes) |
| Overwrite | Calling resolve again with `generate_pin: true` for the same session_id overwrites the previous PIN |
| Storage | In-memory only (`session_unlock._UNLOCK_PINS`); does not persist across server restarts |

---

## API Reference

### `EscalationResolveRequest` fields relevant to PIN unlock

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `generate_pin` | `bool` | `false` | Generate OTP, freeze session, include `unlock_pin` in response |
| `intervention_notes` | `string \| null` | `null` | Appended to student profile `intervention_history` |
| `generate_proposal` | `bool` | `false` | Mark the intervention notes entry for night-cycle proposal generation |

Full endpoint documentation: [`POST /api/escalations/{escalation_id}/resolve`](../2-syscalls/lumina-api-server.md#post-apiscalationssescalation_idresolve)

### `POST /api/sessions/{session_id}/unlock`

Full endpoint documentation: [`POST /api/sessions/{session_id}/unlock`](../2-syscalls/lumina-api-server.md#post-apisessionssession_idunlock)

---

## Auth Requirements

| Operation | Required Role |
|-----------|--------------|
| Resolve escalation with `generate_pin: true` | `root`, `domain_authority` |
| `POST /api/sessions/{session_id}/unlock` | Any authenticated user |
| Chat-path PIN entry | No token required (mirrors `/api/chat` auth) |

---

## SEE ALSO

- [`docs/2-syscalls/lumina-api-server.md`](../2-syscalls/lumina-api-server.md) — Full endpoint reference including frozen-session behaviour
- [`docs/7-concepts/domain-role-hierarchy.md`](../7-concepts/domain-role-hierarchy.md) — `receive_escalations` scoped capability and smart routing
- [`domain-packs/education/schemas/student-profile-schema-v1.json`](../../domain-packs/education/schemas/student-profile-schema-v1.json) — Canonical student profile schema
- [`docs/8-admin/rbac-administration.md`](rbac-administration.md) — Role and permission management
