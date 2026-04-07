---
version: 1.0.0
last_updated: 2026-04-05
---

# Escalation Auto-Freeze

When an escalation fires in a learning module, the student's session is
**immediately frozen** — the chat input is locked and a 6-digit PIN is
required to resume.

## Flow

1. Orchestrator detects escalation condition (ZPD drift, safety violation)
2. `system_log_writer.write_escalation_record()` appends the escalation to logs
3. **Auto-freeze injection** (same call): if `domain_physics.auto_freeze_on_escalation`
   is `true` (default), the session container is frozen and a PIN is generated
4. `processing.py` overrides `result["action"]` to `"session_frozen"` when the
   container is frozen
5. Frontend (`app.tsx`) receives `action === "session_frozen"` or
   `escalated === true` and locks the UI

## Opting Out

Modules can disable auto-freeze by setting:

```json
"auto_freeze_on_escalation": false
```

in their `domain-physics.json`. The Student Commons uses this — only the
`safety_intervene` standing order freezes the session (via its own
`auto_freeze: true` flag).

## Unlock

Teachers issue a PIN via the `resolve_escalation` admin command. The student
enters the 6-digit PIN in the chat input. See `src/lumina/core/session_unlock.py`.

## Files

- `src/lumina/orchestrator/system_log_writer.py` — auto-freeze injection
- `src/lumina/api/processing.py` — action override
- `src/web/app.tsx` — frontend freeze detection
- `src/lumina/core/session_unlock.py` — PIN generation + validation
