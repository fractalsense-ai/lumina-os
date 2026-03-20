---
version: 1.0.0
last_updated: 2026-03-20
---

# persistence_adapter(3)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

## NAME

`persistence_adapter.py` — Abstract persistence interface for runtime and System Log operations

## SYNOPSIS

```python
from persistence_adapter import PersistenceAdapter
```

## ABSTRACT METHODS

### Domain & Session

| Method | Returns | Description |
|--------|---------|-------------|
| `load_domain_physics(path)` | `dict` | Load domain physics document |
| `load_subject_profile(path)` | `dict` | Load subject profile document |
| `get_log_ledger_path(session_id)` | `str` | Stable ledger path for a session |
| `append_log_record(session_id, record, ledger_path)` | `None` | Append one System Log record |
| `load_session_state(session_id)` | `dict | None` | Load persisted session metadata |
| `save_session_state(session_id, state)` | `None` | Persist session metadata |
| `list_log_session_ids()` | `list[str]` | Return known System Log session IDs |
| `validate_log_chain(session_id)` | `dict` | Validate System Log hash-chain integrity |
| `has_policy_commitment(subject_id, subject_version, subject_hash)` | `bool` | Check System Log for matching CommitmentRecord |

### User & Auth

| Method | Returns | Description |
|--------|---------|-------------|
| `create_user(user_id, username, password_hash, role, governed_modules)` | `dict` | Create a new user |
| `get_user(user_id)` | `dict | None` | Get user by ID |
| `get_user_by_username(username)` | `dict | None` | Get user by username |
| `list_users()` | `list[dict]` | List all users (hashes excluded) |
| `update_user_role(user_id, role, governed_modules)` | `dict | None` | Update user role |
| `deactivate_user(user_id)` | `bool` | Soft-delete a user |

## IMPLEMENTATIONS

- `NullPersistenceAdapter` — In-memory no-op (tests)
- `FilesystemPersistenceAdapter` — File-backed JSON/JSONL storage
- `SQLitePersistenceAdapter` — SQLAlchemy async + SQLite

## SEE ALSO

[lumina-api-server(2)](../2-syscalls/lumina-api-server.md)
