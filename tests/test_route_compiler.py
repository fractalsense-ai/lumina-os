"""Tests for lumina.core.route_compiler — pre-compiled execution routes."""

from __future__ import annotations

import pytest
from lumina.core.route_compiler import (
    CompiledRoutes,
    InvariantRoute,
    RouteCompilationError,
    StandingOrderRoute,
    compile_execution_routes,
)


# ── Fixtures ─────────────────────────────────────────────────

def _base_physics(**overrides):
    """Minimal domain-physics dict with one invariant + one standing order."""
    physics = {
        "id": "domain/test/v1",
        "invariants": [
            {
                "id": "inv_1",
                "severity": "warning",
                "check": "score >= 0.5",
                "standing_order_on_violation": "so_retry",
            }
        ],
        "standing_orders": [
            {
                "id": "so_retry",
                "action": "retry",
                "max_attempts": 3,
                "escalation_on_exhaust": False,
            }
        ],
    }
    physics.update(overrides)
    return physics


# ── Auto-compile (no explicit precompiled_routes) ────────────

class TestAutoCompile:
    def test_auto_compiles_invariant_route(self):
        compiled = compile_execution_routes(_base_physics(), strict=False)
        assert compiled.has_routes
        route = compiled.invariant_route("inv_1")
        assert route is not None
        assert route.standing_order_id == "so_retry"
        assert route.tool_adapter_id is None
        assert route.library_deps == ()

    def test_auto_skips_handled_by(self):
        physics = _base_physics()
        physics["invariants"][0]["handled_by"] = "subsystem_x"
        compiled = compile_execution_routes(physics, strict=False)
        assert compiled.invariant_route("inv_1") is None

    def test_auto_skips_no_violation_ref(self):
        physics = _base_physics()
        del physics["invariants"][0]["standing_order_on_violation"]
        compiled = compile_execution_routes(physics, strict=False)
        assert compiled.invariant_route("inv_1") is None

    def test_domain_id_propagated(self):
        compiled = compile_execution_routes(_base_physics())
        assert compiled.domain_id == "domain/test/v1"


# ── Explicit precompiled_routes ──────────────────────────────

class TestExplicitRoutes:
    def _physics_with_routes(self):
        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "invariant_handlers": {
                    "inv_1": {
                        "standing_order_id": "so_retry",
                        "tool_adapter_id": "tool_a",
                        "library_deps": ["lib_x"],
                    }
                },
                "standing_order_tools": {
                    "so_retry": {
                        "tool_chain": ["tool_a", "tool_b"],
                        "library_deps": ["lib_x"],
                    }
                },
            }
        }
        return physics

    def test_invariant_handler_compiled(self):
        tool_idx = {"tool_a": {}, "tool_b": {}}
        lib_idx = {"lib_x": {}}
        compiled = compile_execution_routes(
            self._physics_with_routes(), tool_idx, lib_idx
        )
        route = compiled.invariant_route("inv_1")
        assert route is not None
        assert route.standing_order_id == "so_retry"
        assert route.tool_adapter_id == "tool_a"
        assert route.library_deps == ("lib_x",)

    def test_standing_order_tools_compiled(self):
        tool_idx = {"tool_a": {}, "tool_b": {}}
        lib_idx = {"lib_x": {}}
        compiled = compile_execution_routes(
            self._physics_with_routes(), tool_idx, lib_idx
        )
        so = compiled.standing_order_tools("so_retry")
        assert so is not None
        assert so.tool_chain == ("tool_a", "tool_b")
        assert so.library_deps == ("lib_x",)

    def test_all_tool_ids(self):
        tool_idx = {"tool_a": {}, "tool_b": {}}
        lib_idx = {"lib_x": {}}
        compiled = compile_execution_routes(
            self._physics_with_routes(), tool_idx, lib_idx
        )
        assert compiled.all_tool_ids() == {"tool_a", "tool_b"}

    def test_all_library_deps(self):
        tool_idx = {"tool_a": {}, "tool_b": {}}
        lib_idx = {"lib_x": {}}
        compiled = compile_execution_routes(
            self._physics_with_routes(), tool_idx, lib_idx
        )
        assert compiled.all_library_deps() == {"lib_x"}


# ── Validation (strict mode) ─────────────────────────────────

class TestStrictValidation:
    def test_unknown_invariant_raises(self):
        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "invariant_handlers": {
                    "nonexistent_inv": {
                        "standing_order_id": "so_retry",
                    }
                }
            }
        }
        with pytest.raises(RouteCompilationError, match="nonexistent_inv"):
            compile_execution_routes(physics, strict=True)

    def test_unknown_standing_order_raises(self):
        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "invariant_handlers": {
                    "inv_1": {
                        "standing_order_id": "missing_so",
                    }
                }
            }
        }
        with pytest.raises(RouteCompilationError, match="missing_so"):
            compile_execution_routes(physics, strict=True)

    def test_unknown_tool_raises(self):
        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "invariant_handlers": {
                    "inv_1": {
                        "standing_order_id": "so_retry",
                        "tool_adapter_id": "missing_tool",
                    }
                }
            }
        }
        with pytest.raises(RouteCompilationError, match="missing_tool"):
            compile_execution_routes(physics, tool_index={"other": {}}, strict=True)

    def test_unknown_library_raises(self):
        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "standing_order_tools": {
                    "so_retry": {
                        "tool_chain": [],
                        "library_deps": ["missing_lib"],
                    }
                }
            }
        }
        with pytest.raises(RouteCompilationError, match="missing_lib"):
            compile_execution_routes(physics, library_index={"other": {}}, strict=True)

    def test_lenient_mode_warns_instead(self):
        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "invariant_handlers": {
                    "nonexistent_inv": {
                        "standing_order_id": "so_retry",
                    }
                }
            }
        }
        # Should NOT raise in lenient mode
        compiled = compile_execution_routes(physics, strict=False)
        assert not compiled.has_routes


# ── CompiledRoutes data structure ─────────────────────────────

class TestCompiledRoutes:
    def test_empty_routes(self):
        cr = CompiledRoutes()
        assert not cr.has_routes
        assert cr.invariant_route("x") is None
        assert cr.standing_order_tools("x") is None
        assert cr.all_tool_ids() == set()
        assert cr.all_library_deps() == set()
        assert cr.invariant_ids == []
        assert cr.standing_order_ids == []

    def test_invariant_route_frozen(self):
        r = InvariantRoute("i1", "so1", "t1", ("l1",))
        assert r.invariant_id == "i1"
        with pytest.raises(AttributeError):
            r.invariant_id = "changed"  # type: ignore[misc]

    def test_standing_order_route_frozen(self):
        r = StandingOrderRoute("so1", ("t1", "t2"), ("l1",))
        assert r.tool_chain == ("t1", "t2")
        with pytest.raises(AttributeError):
            r.standing_order_id = "changed"  # type: ignore[misc]


# ── ActorResolver integration ─────────────────────────────────

class TestActorResolverWithCompiledRoutes:
    def test_resolver_accepts_compiled_routes(self):
        from lumina.orchestrator.actor_resolver import ActorResolver

        physics = _base_physics()
        compiled = compile_execution_routes(physics, strict=False)
        resolver = ActorResolver(physics, compiled_routes=compiled)
        assert resolver._compiled_routes is compiled

    def test_resolver_populates_tool_chain(self):
        from lumina.orchestrator.actor_resolver import ActorResolver

        physics = _base_physics()
        physics["execution_policy"] = {
            "precompiled_routes": {
                "standing_order_tools": {
                    "so_retry": {
                        "tool_chain": ["tool_a"],
                        "library_deps": [],
                    }
                }
            }
        }
        compiled = compile_execution_routes(physics, strict=False)
        resolver = ActorResolver(physics, compiled_routes=compiled)

        # Trigger invariant failure → standing order
        results = resolver.check_invariants({"score": 0.1})
        action, esc, trigger = resolver.resolve(results, {})
        assert action == "so_retry"
        assert resolver.last_tool_chain == ("tool_a",)

    def test_resolver_backward_compat_no_routes(self):
        from lumina.orchestrator.actor_resolver import ActorResolver

        physics = _base_physics()
        resolver = ActorResolver(physics)
        results = resolver.check_invariants({"score": 0.1})
        action, esc, trigger = resolver.resolve(results, {})
        assert action == "so_retry"
        assert resolver.last_tool_chain is None

    def test_so_index_o1_lookup(self):
        """Standing-order lookup uses O(1) index instead of linear scan."""
        from lumina.orchestrator.actor_resolver import ActorResolver

        physics = _base_physics()
        resolver = ActorResolver(physics)
        assert "so_retry" in resolver._so_index
        assert resolver._so_index["so_retry"]["id"] == "so_retry"
        # Also indexed by action
        assert "retry" in resolver._so_index
