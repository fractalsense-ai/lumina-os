---
version: 1.0.0
last_updated: 2026-04-05
---

# Student Commons

The **Student Commons** is the default landing module for students who have not yet
been assigned to a specific curriculum module (e.g. algebra, pre-algebra).

## Purpose

- Safe journaling and self-expression space
- Interest exploration and learning-goal reflection
- Module discovery and assignment requests
- Profile viewing

## Key Design Decisions

| Decision | Choice |
|---|---|
| Grading / ZPD | **None** — no evaluation, no mastery tracking |
| Escalation | **Safety-only** — self-harm, violence, abuse, illegal content |
| Auto-freeze on escalation | **Off** by default (`auto_freeze_on_escalation: false`) except safety standing orders which set `auto_freeze: true` individually |
| Journaling style | **Hybrid** — passive initially, gentle prompts after 3 idle turns |
| Persona | Warm, supportive mentor (`student-commons-persona-v1.md`) |

## Invariants

Only one invariant applies:

- **`content_safety_hard`** — hard-safety gate for self-harm, violence, abuse, and
  illegal content. Triggers immediate teacher escalation with session freeze.

## Standing Orders

- **`safety_intervene`** — escalate to teacher within 5 minutes, freeze session
- **`journal_prompt_offer`** — after 3 turns without a clear goal, offer a
  reflection prompt from configured categories

## Student Commands

Students can issue the following commands via natural language:

- **`request_module_assignment`** — request enrolment in a curriculum module
  (creates HITL escalation for teacher/DA approval)
- **`view_available_modules`** — list education modules (`list_modules`)
- **`view_my_profile`** — show non-sensitive profile data

## Module Physics

See: `domain-packs/education/modules/general-education/domain-physics.json`

## Routing

New students are routed here via `role_to_default_module` in
`domain-packs/education/cfg/runtime-config.yaml`:

```yaml
role_to_default_module:
  student: domain/edu/general-education/v1
```

The student profile template (`profiles/student.yaml`) does **not** set a
`domain_id`, so role-based routing applies by default.
