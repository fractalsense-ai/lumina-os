---
version: 1.0.0
last_updated: 2026-04-05
---

# Student Commons

See [education domain docs](../../domain-packs/education/docs/7-concepts/student-commons.md)
for full details.

The Student Commons (`domain/edu/general-education/v1`) is the default landing
module for students. It provides a safe journaling and self-expression space
with no academic grading, ZPD monitoring, or fluency tracking.

## Key Properties

- **No evaluation** — `off_task_ratio` and `correctness` are always neutral
- **Safety-only escalation** — hard-safety invariant (`content_safety_hard`)
- **Hybrid journaling** — passive first, gentle prompts after 3 idle turns
- **Student commands** — request modules, view profile, list modules
- **No auto-freeze** — except on safety escalations

## Routing

Students reach the commons via `role_to_default_module` mapping:

```
user → student → domain/edu/general-education/v1
```

The `_SYSTEM_ROLE_TO_DOMAIN_ROLE` map in `config.py` translates the JWT
`role: "user"` to domain role `"student"`, which then resolves to the
general-education module.
