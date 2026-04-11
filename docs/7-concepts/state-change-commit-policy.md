---
version: 1.0.0
last_updated: 2026-03-20
---

# State-Change Commit Policy

**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-03-20

---

## Overview

Every API endpoint that mutates persistent state **must** write at least one
System Log record before returning a successful response. This is enforced at
two levels ("belt and suspenders"):

| Layer | Mechanism | Location |
|-------|-----------|----------|
| **Runtime** | `@requires_log_commit` decorator | `lumina.system_log.commit_guard` |
| **Static** | AST-based audit scanner | `lumina.system_log.audit_scanner` |

## Runtime Enforcement

### The `@requires_log_commit` Decorator

Applied to every state-mutating endpoint, this decorator:

1. Sets a `_log_commit_pending` context variable at the start of the request.
2. Awaits the wrapped endpoint handler.
3. On **successful return**, checks that `_log_commit_satisfied` was set.
   If not, raises `LogCommitMissing`.
4. On **exception**, skips the check — the error path is not required to
   produce a log record.

```python
from lumina.system_log.commit_guard import requires_log_commit

@router.post("/example")
@requires_log_commit
async def my_endpoint(request: Request):
    # ... perform mutation ...
    _cfg.PERSISTENCE.append_log_record(session_id, record)
    return {"status": "ok"}
```

### Persistence Integration

All three persistence adapters (`FilesystemPersistenceAdapter`,
`SQLitePersistenceAdapter`, `NullPersistenceAdapter`) call
`notify_log_commit()` inside their `append_log_record` and
`append_system_log_record` methods. This automatically satisfies the
decorator's check whenever a log record is written.

### Context Variable Isolation

The guard uses Python `contextvars` so that concurrent requests each track
their own pending/satisfied state independently.

## Static Audit Scanner

### `audit_scanner.py`

A standalone scanner that can be run from the command line or imported in tests:

```bash
# AST-based scan (no imports, fast)
python -m lumina.system_log.audit_scanner

# Runtime scan (imports modules, checks attributes)
python -m lumina.system_log.audit_scanner --runtime
```

The scanner maintains a `STATE_MUTATING_ENDPOINTS` registry — a dict mapping
each route module name to a set of function names that must carry the
decorator. If any registered endpoint is missing the decorator, the scanner
reports it as *unguarded*.

### CI Integration

The test suite includes `test_commit_guard.py` which runs the AST scanner
against the live source tree:

```python
def test_all_state_mutating_endpoints_guarded(self):
    unguarded = scan_source_ast(ROUTES_DIR)
    assert not unguarded
```

Any new state-mutating endpoint that is added without the decorator will
cause this test to fail.

## Covered Endpoints

| Module | Endpoint | Log Record Type |
|--------|----------|----------------|
| `auth` | `register` | TraceEvent (`user_registered`) |
| `auth` | `update_user` | CommitmentRecord |
| `auth` | `delete_user` | CommitmentRecord |
| `auth` | `revoke_token` | CommitmentRecord |
| `auth` | `password_reset` | CommitmentRecord |
| `auth` | `invite_user` | CommitmentRecord |
| `auth` | `setup_password` | CommitmentRecord |
| `staging` | `create_staged_file` | IngestionRecord |
| `staging` | `approve_staged_file` | CommitmentRecord |
| `staging` | `reject_staged_file` | CommitmentRecord |
| `ingestion` | `ingest_commit` | IngestionRecord |
| `domain` | `domain_pack_commit` | CommitmentRecord |
| `domain` | `update_domain_physics` | CommitmentRecord |
| `domain` | `close_session` | TraceEvent |
| `domain_roles` | `assign_domain_role` | CommitmentRecord |
| `domain_roles` | `revoke_domain_role` | CommitmentRecord |
| `admin` | `resolve_escalation` | CommitmentRecord |
| `admin` | `manifest_regen` | CommitmentRecord |
| `admin` | `admin_command` | CommitmentRecord |
| `admin` | `admin_command_resolve` | CommitmentRecord |
| `chat` | `chat` | TraceEvent |
| `admin` | `daemon_resolve_proposal` | CommitmentRecord |

## Adding a New State-Mutating Endpoint

1. Add `@requires_log_commit` to the endpoint function (below `@router.*`).
2. Ensure the handler writes at least one log record via persistence.
3. Add the function name to `STATE_MUTATING_ENDPOINTS` in `audit_scanner.py`.
4. Run `python -m pytest tests/test_commit_guard.py -q` to verify.
