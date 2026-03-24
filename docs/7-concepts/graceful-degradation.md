---
version: 1.0.0
last_updated: 2026-03-20
---

# Graceful Degradation

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-20  

---

## Overview

Graceful Degradation is the pattern used in the admin command pipeline to
convert hard failures into actionable clarification cards.  When the SLM
produces a command that fails schema validation or contains ambiguous
parameters, the system returns a structured response explaining what went
wrong and how to fix it, rather than silently swallowing the error or
returning a bare HTTP error code.

**Problem:** The SLM is probabilistic.  It may output domain-specific role
names (`student`, `teacher`) that are not valid system roles, omit required
fields like `governed_modules`, or produce ambiguous values like `"all"`.
Previously, these failures were caught by a generic `except` block and
silently discarded — the user saw a normal LLM response with no indication
that their admin command was lost.

**Solution:** The auto-stage pipeline now inspects validation errors,
generates a clarification card with actionable hints, and returns it as
`structured_content` so the user can correct the command.

---

## Architecture

### Pipeline Flow

```
Natural language → SLM parse → _normalize_slm_command() → Schema validation
                                                               │
                                        ┌──────────────────────┴──────────┐
                                        ▼                                 ▼
                                   Valid command                   ValueError
                                        │                                │
                                   _stage_command()           _build_clarification_response()
                                        │                                │
                                   HITL proposal card           Clarification card
```

### Clarification Card Structure

```json
{
  "type": "action_card",
  "card_type": "clarification_needed",
  "operation": "invite_user",
  "error": "Command schema validation failed: ...",
  "hints": [
    "'student' is a domain role, not a system role. The system role should be 'user'.",
    "Available domains: education (Education), agriculture (Agriculture)"
  ],
  "original_params": { "username": "alice", "role": "student" }
}
```

### Hint Generation

The `_build_clarification_response()` helper inspects the error message and
original parameters to generate context-aware hints:

| Error Pattern                      | Hint                                                    |
|-----------------------------------|---------------------------------------------------------|
| Schema validation + domain role    | Suggests mapping to `user` with domain role assignment  |
| Empty `governed_modules`           | Lists available domains from the registry               |
| Unknown domain                     | Lists available domains                                 |
| Generic failure                    | Echoes the error and suggests rephrasing                |

---

## HITL-Exempt Operations

Read-only discovery operations (`list_domains`, `list_modules`,
`list_escalations`, `module_status`, etc.) bypass both HITL staging and the
clarification flow.  They execute immediately and return results inline.
These operations are defined in the `_HITL_EXEMPT_OPS` frozenset.

---

## SLM Standing Orders

The system-core domain-physics includes a `slm_command_translation_guidance`
standing order that instructs the SLM to:

1. Map domain-specific roles to the system role `user`
2. Strip domain prefixes from role names
3. Resolve `governed_modules: "all"` to concrete module IDs
4. Request clarification when the domain is ambiguous

This reduces the frequency of clarification cards by catching common
SLM errors at the normalization stage.

---

## SEE ALSO

command-execution-pipeline(7), domain-role-hierarchy(7), rbac-spec-v1(5)
