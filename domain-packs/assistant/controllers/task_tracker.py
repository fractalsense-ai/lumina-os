"""Task tracker utility for the assistant domain.

Manages task lifecycle (open → completed | abandoned | deferred) and
provides helpers for the runtime_adapters domain_step to update task
state consistently.

This is a pure-function utility — no I/O, no persistence.  State is
passed in and returned; the caller (domain_step) is responsible for
writing the result back to the profile.
"""

from __future__ import annotations

import time
from typing import Any


# ── Task status constants ─────────────────────────────────
OPEN = "open"
COMPLETED = "completed"
ABANDONED = "abandoned"
DEFERRED = "deferred"
CONTINUED = "continued"

_TERMINAL = frozenset({COMPLETED, ABANDONED})
_VALID_STATUSES = frozenset({OPEN, COMPLETED, ABANDONED, DEFERRED, CONTINUED})


def new_task(intent_type: str, task_id: str | None = None) -> dict[str, Any]:
    """Create a new task record."""
    return {
        "task_id": task_id or f"task-{int(time.time() * 1000)}",
        "intent_type": intent_type,
        "status": OPEN,
        "turn_count": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def update_task(
    task: dict[str, Any],
    new_status: str,
) -> dict[str, Any]:
    """Transition a task to a new status.

    Returns the updated task dict (shallow copy).  Invalid transitions
    are silently ignored (task returned unchanged).
    """
    if new_status not in _VALID_STATUSES:
        return task

    current = task.get("status", OPEN)
    # Cannot transition out of a terminal state
    if current in _TERMINAL:
        return task

    updated = {**task, "status": new_status, "updated_at": time.time()}
    if new_status == CONTINUED or new_status == OPEN:
        updated["turn_count"] = task.get("turn_count", 0) + 1
    return updated


def is_terminal(task: dict[str, Any]) -> bool:
    """Check whether a task is in a terminal state."""
    return task.get("status") in _TERMINAL


def active_tasks(task_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return non-terminal tasks from a history list."""
    return [t for t in task_history if not is_terminal(t)]
