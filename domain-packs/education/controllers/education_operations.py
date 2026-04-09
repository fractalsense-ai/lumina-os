"""Education domain operation handlers for the admin command pipeline.

Each handler follows the domain-pack handler signature:

    async def handler(operation, params, user_data, ctx) -> dict

This module is loaded dynamically by the admin operation handler registry
via ``runtime-config.yaml → operation_handlers``.  Individual handlers
live in the ``ops/`` sub-package; this file is the slim dispatcher.

See docs/7-concepts/command-execution-pipeline.md
See docs/7-concepts/domain-adapter-pattern.md
"""

from __future__ import annotations

from typing import Any

from .ops.assignments import (
    request_module_assignment,
    request_ta_assignment,
    request_teacher_assignment,
)
from .ops.modules import assign_module, remove_module, switch_active_module
from .ops.roster import assign_student, remove_student

_HANDLERS: dict[str, Any] = {
    "request_module_assignment": request_module_assignment,
    "assign_student": assign_student,
    "remove_student": remove_student,
    "request_teacher_assignment": request_teacher_assignment,
    "request_ta_assignment": request_ta_assignment,
    "assign_module": assign_module,
    "remove_module": remove_module,
    "switch_active_module": switch_active_module,
}


async def handle_operation(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """Route an education-domain admin operation.

    Returns a result dict if the operation is handled, or ``None``
    if *operation* is not an education operation (so the system
    dispatcher can continue with its own elif chain).
    """
    handler = _HANDLERS.get(operation)
    if handler is None:
        return None
    return await handler(operation, params, user_data, ctx)
