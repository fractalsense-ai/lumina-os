---
version: 1.0.0
last_updated: 2026-03-20
---

# Domain Role Hierarchy

**Version:** 1.1.0
**Status:** Active
**Last updated:** 2026-03-19

---

## Overview

Domain Role Hierarchy is an extension to Lumina's RBAC system that allows each domain to define its own role tiers beneath the Domain Authority ceiling. While the 7 system-level roles (`root`, `domain_authority`, `it_support`, `qa`, `auditor`, `user`, `guest`) provide coarse-grained access control across the entire system, domain roles provide fine-grained access control *within* a specific domain.

**Problem:** In an education deployment, a department head (Domain Authority), teachers, teaching assistants, and students all need different levels of access to the same domain module. The system-level `user` role treats them all identically. An enterprise deployment has the same challenge with managers, team leads, and employees.

**Solution:** Each domain-physics document can declare an optional `domain_roles` block that defines a hierarchy of roles scoped to that domain. These roles integrate with the existing JWT and permission resolution system as an additive overlay.

---

## Design Principles

1. **Additive overlay** — System roles are the base layer. Domain roles refine access within a domain but never exceed the ceiling set by the system role they map to.

2. **DA is always the ceiling** — The Domain Authority is implicitly hierarchy level 0 within their domain. No domain role can grant more access than the DA has. Domain roles start at hierarchy level 1.

3. **Backward-compatible** — The `domain_roles` block is optional. Domains without it work exactly as before. Domain roles are purely additive.

4. **Domain-scoped** — A domain role exists only within its domain. A user can be a `teacher` in algebra and a `student` in geometry. There is no cross-domain inheritance.

---

## How It Works

### Defining Domain Roles

Domain roles are declared in the `domain_roles` block of a domain-physics document:

```json
{
  "domain_roles": {
    "schema_version": "1.0",
    "roles": [
      {
        "role_id": "teacher",
        "role_name": "Teacher",
        "hierarchy_level": 1,
        "description": "Instructor with full domain access.",
        "maps_to_system_role": "domain_authority",
        "default_access": "rwx",
        "may_assign_domain_roles": true,
        "max_assignable_level": 2,
        "scoped_capabilities": {
          "receive_escalations": true,
          "view_all_student_progress": true
        }
      },
      {
        "role_id": "teaching_assistant",
        "role_name": "Teaching Assistant",
        "hierarchy_level": 2,
        "description": "Support staff with read and execute access.",
        "maps_to_system_role": "user",
        "default_access": "rx"
      },
      {
        "role_id": "student",
        "role_name": "Student",
        "hierarchy_level": 3,
        "description": "Learner with execute-only access.",
        "maps_to_system_role": "user",
        "default_access": "x"
      }
    ],
    "role_acl": [
      {
        "domain_role": "teaching_assistant",
        "access": "r",
        "scope": "log_records_own_students"
      }
    ]
  }
}
```

### Role Definition Fields

| Field | Required | Description |
|-------|----------|-------------|
| `role_id` | yes | Unique identifier within the domain (lowercase_snake_case) |
| `role_name` | yes | Human-readable display name |
| `hierarchy_level` | yes | Position in hierarchy (1-10, DA is implicit 0) |
| `description` | yes | Purpose and responsibilities |
| `maps_to_system_role` | yes | System role ceiling (`domain_authority`, `user`, or `guest`) |
| `default_access` | yes | Default `rwxi` permissions within the domain |
| `may_assign_domain_roles` | no | Can this role assign domain roles to others? (default: false) |
| `max_assignable_level` | no | Lowest privilege level this role can assign (only when `may_assign_domain_roles` is true) |
| `scoped_capabilities` | no | Free-form boolean flags for domain-specific capability checks |

### System Role Mapping

Each domain role maps to a system role via `maps_to_system_role`. This determines the maximum possible permissions the domain role can be granted:

| System Role | Use For | Ceiling |
|-------------|---------|---------|
| `domain_authority` | Sub-DA roles like teachers, managers | Full rwx possible |
| `user` | Operational roles like TAs, field operators | Based on module ACL |
| `guest` | Limited-access domain roles | Read and/or execute only |

Cross-cutting system roles (`root`, `it_support`, `qa`, `auditor`) cannot be used as mappings because they have independent system-wide scope.

### JWT Integration

Domain roles are carried in the JWT as a `domain_roles` claim mapping module IDs to role IDs:

```json
{
  "sub": "user_ta_001",
  "role": "user",
  "governed_modules": [],
  "domain_roles": {
    "domain/edu/algebra-level-1/v1": "teaching_assistant",
    "domain/edu/geometry-level-1/v1": "student"
  }
}
```

A user can hold different domain roles in different modules.

### Permission Resolution

The permission checker runs domain role resolution as step 7, after all system-level checks:

```
1. Root bypass                                    → ALLOW
2-5. System-level mode check (owner/group/others) → ALLOW if permitted
6. System-level ACL check                         → ALLOW if permitted
7. Domain role check                              → ALLOW if permitted
   a. Look up domain_role in domain_roles.roles
   b. Check default_access for the operation
   c. Check role_acl entries for the domain_role
   d. Check permissions.acl for domain_role entries
8. DENY
```

Domain roles are purely additive. They can grant access that the system role alone would deny, but they cannot revoke access already granted by system-level checks.

---

## Domain Examples

### Education

| Domain Role | Level | System Mapping | Access | Description |
|-------------|-------|----------------|--------|-------------|
| *(Domain Authority)* | *0* | *domain_authority* | *rwx* | Department head — implicit ceiling |
| `teacher` | 1 | `domain_authority` | rwx | Instructor; receives escalations; can assign TAs and students; may freeze/unfreeze student sessions via PIN unlock |
| `teaching_assistant` | 2 | `user` | rx | Support staff, can view student progress and issue hints |
| `student` | 3 | `user` | x | Learner, execute sessions only |

### Agriculture

| Domain Role | Level | System Mapping | Access | Description |
|-------------|-------|----------------|--------|-------------|
| *(Domain Authority)* | *0* | *domain_authority* | *rwx* | Lead operations manager — implicit ceiling |
| `site_manager` | 1 | `domain_authority` | rwx | On-site manager, can assign operators and observers |
| `field_operator` | 2 | `user` | rx | Field workers who execute procedures and log observations |
| `observer` | 3 | `user` | r | Read-only observers |

### Enterprise (Example)

| Domain Role | Level | System Mapping | Access | Description |
|-------------|-------|----------------|--------|-------------|
| *(Domain Authority)* | *0* | *domain_authority* | *rwx* | VP / Director — implicit ceiling |
| `manager` | 1 | `domain_authority` | rwx | Department managers |
| `team_lead` | 2 | `user` | rx | Team leads with monitoring access |
| `employee` | 3 | `user` | x | Standard employees |

### Healthcare (Example)

| Domain Role | Level | System Mapping | Access | Description |
|-------------|-------|----------------|--------|-------------|
| *(Domain Authority)* | *0* | *domain_authority* | *rwx* | Chief physician — implicit ceiling |
| `attending_physician` | 1 | `domain_authority` | rwx | Lead physician with full clinical authority |
| `resident` | 2 | `domain_authority` | rx | Physicians in training |
| `nurse` | 3 | `user` | rx | Nursing staff |
| `patient` | 4 | `user` | x | Patients in guided interactions |

---

## Scoped Capabilities

The `scoped_capabilities` field provides domain-specific boolean flags that go beyond the `rwxi` permission model. These are consulted by domain runtime code for fine-grained capability checks:

```json
"scoped_capabilities": {
  "receive_escalations": true,
  "view_all_student_progress": true,
  "modify_standing_orders": false,
  "issue_hints": true
}
```

Capabilities are free-form and domain-defined. They are not enforced by the permission checker itself but by domain-specific code paths (e.g., the escalation engine checks `receive_escalations` to determine who receives escalation packets).

### Smart escalation routing via `receive_escalations`

When `receive_escalations: true` is set on a domain role and a student profile's `assigned_teacher_id` is populated with the actor ID of a user holding that role, the orchestrator automatically populates `escalation_target_id` in every escalation record written for that student. This routes the escalation directly to the named teacher in dashboards and notification systems without requiring manual triage.

`assigned_room_id` in the student profile is also carried into the escalation record as `assigned_room_id`, giving classroom-level context to multi-room deployments. See [escalation-pin-unlock](../8-admin/escalation-pin-unlock.md) for the full teacher-student freeze/unlock workflow.

---

## Student Profile Assignment Fields

The education domain student profile (`domain-packs/education/schemas/student-profile-schema-v1.json`) includes two fields that connect students to their domain role holders:

| Field | Type | Description |
|-------|------|-------------|
| `assigned_teacher_id` | `string \| null` | Actor ID of the teacher responsible for this student. Populated at registration or role-assignment time. Used by the orchestrator to set `escalation_target_id` in escalation records. |
| `assigned_room_id` | `string \| null` | Classroom or cohort identifier. Carried into escalation records for routing and reporting. |

These fields are set by the Domain Authority (or a teacher with `may_assign_domain_roles: true`) when assigning a student role. They are stored in the persistence backend alongside the rest of the student profile and are read by `ppa_orchestrator._write_escalation_record()` at escalation time.

---

## Role Assignment

Domain roles are assigned by the Domain Authority or by roles with `may_assign_domain_roles: true`. Assignments are recorded in the System Logs as `domain_role_assignment` commitment records for full auditability.

A role can only assign roles at or below its `max_assignable_level`. For example, a teacher at level 1 with `max_assignable_level: 2` can assign teaching assistants (level 2) and students (level 3) but not other teachers (level 1).

---

## System Roles and Domain Default Routing

Cross-cutting system roles (`root`, `it_support`, `qa`, `auditor`) operate across all domains and are outside the domain role hierarchy.  However, they interact with domain routing in two specific ways:

### role_defaults

`root` and `it_support` users have a **default domain** of `system` when no explicit `domain_id` is provided in a request and NLP routing does not confidently match another domain.  This is declared in `cfg/domain-registry.yaml`:

```yaml
role_defaults:
  root: system
  it_support: system
```

All other system roles (`qa`, `auditor`, `user`), as well as unauthenticated users, fall through to the global `default_domain` (currently `education`), masking system internals from domain-level users by default.

### domain_authority governed_modules inference

`domain_authority` users do not appear in `role_defaults` because they are domain-affiliated, not system operators.  Instead, when NLP routing finds no confident match, their default domain is **inferred from their `governed_modules` JWT claim**:

The system extracts the module-prefix segment from the first module path (`domain/<prefix>/…`) and looks it up in the `module_prefix` reverse map in the registry.  A teacher with `governed_modules: ["domain/edu/algebra-level-1/v1"]` defaults to `education`; an agriculture domain authority with `governed_modules: ["domain/agri/operations-level-1/v1"]` defaults to `agriculture`.

If `governed_modules` is empty or the prefix is unrecognised, the global `default_domain` is used.

This design is implemented in `DomainRegistry.resolve_default_for_user()` in `src/lumina/core/domain_registry.py`.

---

## Groups — Bridging Domain Roles to chmod Permissions

Domain packs define **named groups** in the `groups` block of a domain-physics document. Groups bridge the gap between domain roles and the chmod-style octal permission model: the `permissions.group` field references a group name, and the kernel checks membership at runtime.

```yaml
groups:
  educators:
    description: "Teaching staff with group-level permissions."
    members:
      domain_roles: [teacher, teaching_assistant]
  learners:
    description: "Students enrolled in the module."
    members:
      domain_roles: [student]

permissions:
  mode: "750"
  owner: "da_algebra_lead_001"
  group: "educators"          # ← references the group above
```

The kernel never interprets the group name semantically — it only checks whether the requesting user's system role or domain role appears in the `members` block. This is analogous to `/etc/group` in UNIX.

If no `groups` block exists, the kernel falls back to matching `permissions.group` literally against the user's system role, preserving backward compatibility.

See [`standards/group-definition-schema-v1.json`](../../standards/group-definition-schema-v1.json) for the formal schema.

---

## SEE ALSO

- [`specs/rbac-spec-v1.md`](../../specs/rbac-spec-v1.md) — Full RBAC specification including domain role hierarchy
- [`standards/domain-role-schema-v1.json`](../../standards/domain-role-schema-v1.json) — JSON schema for domain role definitions
- [`standards/rbac-permission-schema-v1.json`](../../standards/rbac-permission-schema-v1.json) — RBAC permission schema (extended with `domain_role` ACL entries)
- [`docs/3-functions/permissions.md`](../3-functions/permissions.md) — Permission checker function reference
- [`docs/3-functions/auth.md`](../3-functions/auth.md) — JWT authentication (domain_roles claim)
- [`docs/8-admin/rbac-administration.md`](../8-admin/rbac-administration.md) — Role management procedures
- [`docs/8-admin/escalation-pin-unlock.md`](../8-admin/escalation-pin-unlock.md) — Teacher-initiated session freeze and PIN unlock workflow
- [`docs/7-concepts/zero-trust-architecture.md`](zero-trust-architecture.md) — Zero-trust architecture
- [`src/lumina/api/routes/admin.py`](../../src/lumina/api/routes/admin.py) — domain-scoped `list_users` filtering and `invite_user` DA access enforcement
- [`domain-packs/system/modules/system-core/domain-physics.json`](../../domain-packs/system/modules/system-core/domain-physics.json) — canonical `min_role_policy` and role hierarchy configuration
