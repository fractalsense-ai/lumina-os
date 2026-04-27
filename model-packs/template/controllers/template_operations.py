"""Template domain — operations dispatcher (slim router).

Each handler follows the domain-pack handler signature:

    async def handler(operation, params, user_data, ctx) -> dict

This module is loaded dynamically by the admin operation handler registry
via ``runtime-config.yaml → operation_handlers``.  Individual handlers
live in the ``ops/`` sub-package; this file is the slim dispatcher.

HOW TO USE:
  1. Create handler functions in ops/ submodules (e.g. ops/roster.py).
  2. Import them here and add entries to _HANDLERS.
  3. Wire this file in runtime-config.yaml:
       adapters:
         operation_handlers:
           module_path: model-packs/template/controllers/template_operations.py
           callable: handle_operation

See docs/7-concepts/command-execution-pipeline.md
See docs/7-concepts/domain-adapter-pattern.md
"""

from __future__ import annotations

from typing import Any

# TODO: Import your handler functions from ops/ submodules:
# from .ops.roster import assign_entity, remove_entity
# from .ops.modules import assign_module, switch_module

_HANDLERS: dict[str, Any] = {
    # TODO: Map operation names to handler callables:
    # "assign_entity": assign_entity,
    # "remove_entity": remove_entity,
    # "assign_module": assign_module,
    # "switch_module": switch_module,
}


async def handle_operation(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """Route a domain admin operation to the appropriate handler.

    Returns a result dict if the operation is handled, or ``None``
    if *operation* is not recognised (so the system dispatcher can
    continue with its own elif chain).
    """
    handler = _HANDLERS.get(operation)
    if handler is None:
        return None
    return await handler(operation, params, user_data, ctx)
