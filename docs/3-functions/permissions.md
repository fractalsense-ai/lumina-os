# permissions(3)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`permissions.py` — chmod-style module permission checker

## SYNOPSIS

```python
from permissions import Operation, check_permission, parse_octal, mode_to_symbolic
```

## CLASSES

### `Operation(IntFlag)`

Permission bits matching UNIX rwx semantics.

- `READ = 4`
- `WRITE = 2`
- `EXECUTE = 1`

## FUNCTIONS

### `parse_octal(mode) → tuple[int, int, int]`

Parse a 3-digit octal mode string into (owner, group, others) bit tuples.

```python
>>> parse_octal("750")
(7, 5, 0)
```

### `check_permission(user_id, user_role, module_permissions, operation) → bool`

Evaluate whether a user may perform an operation on a module.

**Resolution order:**
1. Root role bypasses all checks → `True`
2. Determine category: owner (user_id match), group (role match), or others
3. Check mode bits for the resolved category
4. Fall back to ACL entries if mode denies

### `check_permission_or_raise(user_id, user_role, module_permissions, operation) → None`

Same as `check_permission` but raises `PermissionError` on denial.

### `mode_to_symbolic(mode) → str`

Convert a 3-digit octal mode to symbolic representation.

```python
>>> mode_to_symbolic("750")
"rwxr-x---"
```

## SEE ALSO

[auth(3)](auth.md), [rbac-spec](../../specs/rbac-spec-v1.md), [rbac-permission-schema](../../standards/rbac-permission-schema-v1.json)
