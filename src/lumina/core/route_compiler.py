"""route_compiler.py — Pre-compile execution routes from domain-physics pointers.

At startup (or domain-pack load), resolves the invariant → standing-order →
tool-adapter → group-library graph into flat lookup tables.  This acts as a
"shader cache": the runtime reads pre-resolved routes with O(1) dict lookups
instead of walking the graph on every turn.

Validates all references at compile time (fail-fast).

Usage::

    from lumina.core.route_compiler import compile_execution_routes
    compiled = compile_execution_routes(domain_physics, tool_index, library_index)
    # compiled.invariant_route("equivalence_preserved")
    # compiled.standing_order_tools("request_more_steps")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("lumina.route-compiler")


# ── Compiled route data structures ───────────────────────────

@dataclass(frozen=True)
class InvariantRoute:
    """Pre-resolved route for a single invariant violation."""
    invariant_id: str
    standing_order_id: str
    tool_adapter_id: str | None = None
    library_deps: tuple[str, ...] = ()


@dataclass(frozen=True)
class StandingOrderRoute:
    """Pre-resolved tool chain for a single standing order."""
    standing_order_id: str
    tool_chain: tuple[str, ...] = ()
    library_deps: tuple[str, ...] = ()


@dataclass
class CompiledRoutes:
    """Flat lookup tables for all pre-compiled execution routes in a module.

    Immutable after compilation — the orchestrator and middleware read
    from these tables on every turn with zero resolution overhead.
    """
    _invariant_routes: dict[str, InvariantRoute] = field(default_factory=dict)
    _standing_order_routes: dict[str, StandingOrderRoute] = field(default_factory=dict)
    domain_id: str = ""

    def invariant_route(self, invariant_id: str) -> InvariantRoute | None:
        """Look up the pre-compiled route for an invariant, or None."""
        return self._invariant_routes.get(invariant_id)

    def standing_order_tools(self, standing_order_id: str) -> StandingOrderRoute | None:
        """Look up the pre-compiled tool chain for a standing order, or None."""
        return self._standing_order_routes.get(standing_order_id)

    @property
    def invariant_ids(self) -> list[str]:
        return list(self._invariant_routes)

    @property
    def standing_order_ids(self) -> list[str]:
        return list(self._standing_order_routes)

    @property
    def has_routes(self) -> bool:
        return bool(self._invariant_routes or self._standing_order_routes)

    def all_library_deps(self) -> set[str]:
        """Return the union of every library dependency across all routes."""
        deps: set[str] = set()
        for r in self._invariant_routes.values():
            deps.update(r.library_deps)
        for r in self._standing_order_routes.values():
            deps.update(r.library_deps)
        return deps

    def all_tool_ids(self) -> set[str]:
        """Return every tool adapter ID referenced across all routes."""
        ids: set[str] = set()
        for r in self._invariant_routes.values():
            if r.tool_adapter_id:
                ids.add(r.tool_adapter_id)
        for r in self._standing_order_routes.values():
            ids.update(r.tool_chain)
        return ids


# ── Compilation errors ───────────────────────────────────────

class RouteCompilationError(Exception):
    """Raised when a physics file references a missing resource."""


# ── Compiler ─────────────────────────────────────────────────

def compile_execution_routes(
    domain_physics: dict[str, Any],
    tool_index: dict[str, Any] | None = None,
    library_index: dict[str, Any] | None = None,
    *,
    strict: bool = True,
) -> CompiledRoutes:
    """Compile execution routes from a domain-physics dict.

    Parameters
    ----------
    domain_physics:
        Parsed domain-physics JSON object.
    tool_index:
        Available tool adapter IDs (keys) for validation.
        Pass ``None`` to skip tool validation.
    library_index:
        Available group library IDs (keys) for validation.
        Pass ``None`` to skip library validation.
    strict:
        When ``True`` (default), missing references raise
        :class:`RouteCompilationError`.  When ``False``, missing
        references are logged as warnings and the route is skipped.

    Returns
    -------
    CompiledRoutes
        Flat lookup tables ready for O(1) runtime access.
    """
    tool_index = tool_index or {}
    library_index = library_index or {}

    domain_id = str(domain_physics.get("id", ""))
    invariants = {inv["id"]: inv for inv in domain_physics.get("invariants", []) if "id" in inv}
    standing_orders = {so["id"]: so for so in domain_physics.get("standing_orders", []) if "id" in so}

    exec_policy = domain_physics.get("execution_policy") or {}
    precompiled = exec_policy.get("precompiled_routes") or {}

    inv_routes: dict[str, InvariantRoute] = {}
    so_routes: dict[str, StandingOrderRoute] = {}
    errors: list[str] = []

    # ── Compile invariant handlers ───────────────────────────
    for inv_id, handler in (precompiled.get("invariant_handlers") or {}).items():
        # Validate the invariant exists
        if inv_id not in invariants:
            errors.append(f"invariant_handlers references unknown invariant '{inv_id}'")
            continue

        so_id = handler.get("standing_order_id", "")
        if so_id and so_id not in standing_orders:
            errors.append(
                f"invariant_handlers[{inv_id}].standing_order_id "
                f"references unknown standing order '{so_id}'"
            )
            continue

        tool_id = handler.get("tool_adapter_id")
        if tool_id and tool_index and tool_id not in tool_index:
            msg = f"invariant_handlers[{inv_id}].tool_adapter_id references unknown tool '{tool_id}'"
            errors.append(msg)
            continue

        lib_deps = tuple(handler.get("library_deps") or [])
        for lib_id in lib_deps:
            if library_index and lib_id not in library_index:
                errors.append(
                    f"invariant_handlers[{inv_id}].library_deps "
                    f"references unknown library '{lib_id}'"
                )

        inv_routes[inv_id] = InvariantRoute(
            invariant_id=inv_id,
            standing_order_id=so_id,
            tool_adapter_id=tool_id,
            library_deps=lib_deps,
        )

    # ── Compile standing-order tool chains ────────────────────
    for so_id, chain_cfg in (precompiled.get("standing_order_tools") or {}).items():
        if so_id not in standing_orders:
            errors.append(f"standing_order_tools references unknown standing order '{so_id}'")
            continue

        tool_chain = tuple(chain_cfg.get("tool_chain") or [])
        for tid in tool_chain:
            if tool_index and tid not in tool_index:
                errors.append(
                    f"standing_order_tools[{so_id}].tool_chain "
                    f"references unknown tool '{tid}'"
                )

        lib_deps = tuple(chain_cfg.get("library_deps") or [])
        for lib_id in lib_deps:
            if library_index and lib_id not in library_index:
                errors.append(
                    f"standing_order_tools[{so_id}].library_deps "
                    f"references unknown library '{lib_id}'"
                )

        so_routes[so_id] = StandingOrderRoute(
            standing_order_id=so_id,
            tool_chain=tool_chain,
            library_deps=lib_deps,
        )

    # ── Auto-compile from physics when no explicit routes declared ─
    # If the physics file has invariants with standing_order_on_violation
    # but no precompiled_routes section, build routes automatically from
    # the invariant → standing_order links.
    if not precompiled:
        for inv in domain_physics.get("invariants", []):
            inv_id = inv.get("id", "")
            so_ref = inv.get("standing_order_on_violation")
            if not inv_id or not so_ref:
                continue
            if inv.get("handled_by"):
                continue  # delegated to subsystem
            if so_ref in standing_orders or any(
                so.get("action") == so_ref for so in domain_physics.get("standing_orders", [])
            ):
                inv_routes[inv_id] = InvariantRoute(
                    invariant_id=inv_id,
                    standing_order_id=so_ref,
                )

    # ── Report or raise ──────────────────────────────────────
    if errors:
        msg = f"Route compilation failed for '{domain_id}': " + "; ".join(errors)
        if strict:
            raise RouteCompilationError(msg)
        log.warning(msg)

    compiled = CompiledRoutes(
        _invariant_routes=inv_routes,
        _standing_order_routes=so_routes,
        domain_id=domain_id,
    )

    log.info(
        "Compiled routes for '%s': %d invariant handlers, %d standing-order chains",
        domain_id,
        len(inv_routes),
        len(so_routes),
    )
    return compiled
