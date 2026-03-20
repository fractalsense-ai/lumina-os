"""
commit_guard.py — Runtime enforcement that state-mutating endpoints write a System Log record.

Provides:
  @requires_log_commit  — decorator for async FastAPI endpoints
  notify_log_commit()   — called by persistence layer when a record is written
  LogCommitMissing      — raised when an endpoint returns without logging
"""

from __future__ import annotations

import contextvars
import functools
import logging
from typing import Any, Callable, TypeVar

log = logging.getLogger("lumina.commit_guard")

F = TypeVar("F", bound=Callable[..., Any])

# ── Context variable ───────────────────────────────────────────
# Holds a mutable dict {"pending": bool, "satisfied": bool} so that
# mutations from thread-pool threads (run_in_threadpool) propagate
# back to the async context that created the signal.
_log_commit_signal: contextvars.ContextVar[dict[str, bool] | None] = contextvars.ContextVar(
    "_log_commit_signal", default=None,
)

# Backward-compat aliases used in tests
_log_commit_pending = _log_commit_signal
_log_commit_satisfied = _log_commit_signal


class LogCommitMissing(RuntimeError):
    """A state-mutating endpoint completed without writing a System Log record."""


def notify_log_commit() -> None:
    """Signal that a System Log record was written during the current request.

    Called automatically by persistence adapters in their ``append_log_record``
    and ``append_system_log_record`` methods.  Safe to call outside of a
    guarded endpoint (no-op when no guard is active).
    """
    signal = _log_commit_signal.get(None)
    if signal is not None and signal["pending"]:
        signal["satisfied"] = True


def is_commit_pending() -> bool:
    """Return True when inside a @requires_log_commit-guarded call."""
    signal = _log_commit_signal.get(None)
    return signal is not None and signal["pending"]


def is_commit_satisfied() -> bool:
    """Return True when a log record has been written inside the current guard."""
    signal = _log_commit_signal.get(None)
    return signal is not None and signal["satisfied"]


def requires_log_commit(fn: F) -> F:
    """Decorator for async endpoints that **must** write at least one System Log record.

    On successful return, if no ``append_log_record`` / ``append_system_log_record``
    call was observed, raises :class:`LogCommitMissing`.  Error paths (exceptions
    raised by the endpoint itself) are *not* checked — only successful mutations
    must leave an audit trail.

    Usage::

        @router.post("/api/staging/create")
        @requires_log_commit
        async def create_staged_file(...):
            ...
    """

    @functools.wraps(fn)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        signal = {"pending": True, "satisfied": False}
        tok = _log_commit_signal.set(signal)
        try:
            result = await fn(*args, **kwargs)
            if not signal["satisfied"]:
                msg = (
                    f"Endpoint '{fn.__name__}' completed successfully without "
                    "writing a System Log record"
                )
                log.error(msg)
                raise LogCommitMissing(msg)
            return result
        except LogCommitMissing:
            raise
        except Exception:
            # Don't enforce on error paths — the operation didn't succeed.
            raise
        finally:
            _log_commit_signal.reset(tok)

    # Preserve a marker so the audit scanner can detect guarded endpoints.
    _wrapper._requires_log_commit = True  # type: ignore[attr-defined]

    return _wrapper  # type: ignore[return-value]
