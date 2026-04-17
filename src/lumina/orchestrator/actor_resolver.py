"""
actor_resolver.py — ActorResolver (the Judge)

Owns all domain-physics decision logic: invariant evaluation, standing-order
attempt tracking, and action/escalation resolution.

The Actor in D.S.A. is whatever changes the state of the system relative to
a domain (student, sensor, farmer — context-dependent).  The orchestrator is
NOT an Actor; it evaluates evidence produced by Actors and resolves the
appropriate standing-order or escalation response.

Extracted from ppa_orchestrator.py so the decision tree can be unit-tested
without mocking a filesystem or ledger.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from lumina.middleware.invariant_checker import evaluate_invariants as _mw_evaluate_invariants

logger = logging.getLogger("lumina.orchestrator.actor_resolver")

if TYPE_CHECKING:
    from lumina.core.route_compiler import CompiledRoutes


class ActorResolver:
    """
    Evaluates invariants and resolves the final (action, escalate, trigger) for a turn.

    Owns:
    - Per-standing-order attempt counters (``_standing_order_attempts``).
    - The ``last_standing_order_id`` / ``last_standing_order_attempt`` diagnostics
      written into each TraceEvent.

    Public interface::

        resolver = ActorResolver(domain_physics)
        invariant_results = resolver.check_invariants(evidence)
        action, escalate, trigger = resolver.resolve(invariant_results, domain_lib_decision)
    """

    def __init__(
        self,
        domain_physics: dict[str, Any],
        compiled_routes: CompiledRoutes | None = None,
    ) -> None:
        self._domain = domain_physics
        self._compiled_routes = compiled_routes
        self._standing_order_attempts: dict[str, int] = {}
        self.last_standing_order_id: str | None = None
        self.last_standing_order_attempt: int | None = None
        self.last_tool_chain: tuple[str, ...] | None = None

        # Build O(1) standing-order index keyed by both 'id' and 'action'.
        self._so_index: dict[str, dict[str, Any]] = {}
        for item in domain_physics.get("standing_orders", []):
            if not isinstance(item, dict):
                continue
            if "id" in item:
                self._so_index[item["id"]] = item
            if "action" in item and item["action"] != item.get("id"):
                self._so_index[item["action"]] = item

    # ── Attempt state management (for session-state persistence) ──

    def set_attempts(self, attempts: dict[str, Any] | None) -> None:
        """Restore standing-order attempt counters from persisted session state."""
        restored: dict[str, int] = {}
        for key, value in (attempts or {}).items():
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                restored[str(key)] = parsed
        self._standing_order_attempts = restored

    def get_attempts(self) -> dict[str, int]:
        """Expose standing-order attempt counters for session-state persistence."""
        return dict(self._standing_order_attempts)

    # ── Invariant evaluation ──────────────────────────────────

    def check_invariants(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Evaluate all domain-pack invariants against the structured evidence dict.

        Delegates to ``lumina.middleware.invariant_checker`` so the expression
        parser lives in exactly one place.

        Returns a list of result dicts:
            {id, severity, passed, standing_order_on_violation, signal_type}
        """
        return _mw_evaluate_invariants(
            self._domain.get("invariants", []), evidence
        )

    # ── Action resolution ─────────────────────────────────────

    def resolve(
        self,
        invariant_results: list[dict[str, Any]],
        domain_lib_decision: dict[str, Any],
    ) -> tuple[str | None, bool, str | None]:
        """
        Determine the final action for this turn.

        Priority order:
          1. Critical invariant failure → its standing_order_on_violation.
          2. Warning invariant failure  → its standing_order_on_violation.
          3. No invariant failure       → domain lib's decision["action"].

        Additionally, if the domain-lib decision marks escalation conditions,
        the second return value is ``True`` (escalate).

        Returns:
            (action, should_escalate, escalation_trigger)
        """
        self.last_standing_order_id = None
        self.last_standing_order_attempt = None
        self.last_tool_chain = None
        for result in invariant_results:
            if result["passed"]:
                so_key = result.get("standing_order_on_violation")
                if so_key and so_key in self._standing_order_attempts:
                    del self._standing_order_attempts[so_key]

        # Critical failures first
        escalation_from_exhaustion: tuple[str | None, bool, str | None] | None = None
        for result in invariant_results:
            if not result["passed"] and result["severity"] == "critical":
                action_result = self._resolve_standing_order_action(
                    result["standing_order_on_violation"]
                )
                if action_result[0] is not None:
                    return action_result
                if action_result[1] and escalation_from_exhaustion is None:
                    escalation_from_exhaustion = action_result

        # Warning failures next
        for result in invariant_results:
            if not result["passed"] and result["severity"] == "warning":
                action_result = self._resolve_standing_order_action(
                    result["standing_order_on_violation"]
                )
                if action_result[0] is not None:
                    return action_result
                if action_result[1] and escalation_from_exhaustion is None:
                    escalation_from_exhaustion = action_result

        if escalation_from_exhaustion is not None:
            return escalation_from_exhaustion

        # Fall through to domain-lib decision
        action = domain_lib_decision.get("action")
        should_escalate = bool(domain_lib_decision.get("should_escalate", False))

        # ── Baseline-before-escalation gate ───────────────────────
        # Domain-lib step functions may set ``escalation_eligible`` to
        # ``False`` while their subsystem baselines are still priming
        # (e.g. first N turns of ZPD drift window, vocabulary baseline
        # lock period).  Metric-driven escalations are suppressed until
        # the baseline is established.  Safety/invariant escalations
        # (standing-order exhaustion) are resolved earlier in this
        # method and are never affected by this gate.
        escalation_eligible = bool(
            domain_lib_decision.get("escalation_eligible", True)
        )
        if should_escalate and not escalation_eligible:
            logger.info(
                "escalation suppressed: subsystem baseline not yet primed "
                "(action=%s, tier=%s)",
                action,
                domain_lib_decision.get("tier"),
            )
            should_escalate = False

        escalation_trigger = "domain_lib_escalation_event" if should_escalate else None
        return action, should_escalate, escalation_trigger

    def _resolve_standing_order_action(
        self, action: str | None
    ) -> tuple[str | None, bool, str | None]:
        """
        Track standing-order attempts and enforce max-attempt escalation policy.

        Returns:
            (action, should_escalate, escalation_trigger)
        """
        if not action:
            return action, False, None

        standing_order = self._so_index.get(action)
        if standing_order is None:
            return action, False, None

        standing_order_id = str(standing_order.get("id", action))
        max_attempts_raw = standing_order.get("max_attempts", 1)
        try:
            max_attempts = int(max_attempts_raw)
        except (TypeError, ValueError):
            max_attempts = 1
        escalate_on_exhaust = bool(standing_order.get("escalation_on_exhaust", False))

        attempt = self._standing_order_attempts.get(standing_order_id, 0) + 1
        self._standing_order_attempts[standing_order_id] = attempt
        self.last_standing_order_id = standing_order_id
        self.last_standing_order_attempt = attempt

        if max_attempts >= 0 and attempt > max_attempts:
            trigger = f"standing_order_exhausted:{standing_order_id}"
            return None, escalate_on_exhaust, trigger if escalate_on_exhaust else None

        # Populate tool chain from compiled routes when available.
        if self._compiled_routes is not None:
            so_route = self._compiled_routes.standing_order_tools(standing_order_id)
            if so_route is not None:
                self.last_tool_chain = so_route.tool_chain

        return action, False, None


# Backward-compatible alias
ActionResolver = ActorResolver
