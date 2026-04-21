"""blackbox_triggers.py — Extensible trigger registry for black-box capture.

Domain packs own the trigger rules.  The core provides infrastructure
and a handful of built-in escalation triggers.  Domain packs can
register custom triggers via::

    from lumina.session.blackbox_triggers import trigger_registry
    trigger_registry.register("resource_runaway", lambda e: e.get("load_score", 0) > 0.9)
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("lumina.blackbox")


class TriggerRegistry:
    """Singleton registry mapping trigger names to predicate functions.

    Each predicate receives an ``event: dict[str, Any]`` and returns
    ``True`` when the trigger condition is met.
    """

    def __init__(self) -> None:
        self._triggers: dict[str, Callable[[dict[str, Any]], bool]] = {}

    def register(self, name: str, condition: Callable[[dict[str, Any]], bool]) -> None:
        """Register a named trigger predicate."""
        self._triggers[name] = condition

    def unregister(self, name: str) -> None:
        """Remove a trigger by name (no-op if absent)."""
        self._triggers.pop(name, None)

    def check(self, event: dict[str, Any]) -> list[str]:
        """Return names of all triggers that fire for *event*."""
        fired: list[str] = []
        for name, fn in self._triggers.items():
            try:
                if fn(event):
                    fired.append(name)
            except Exception:
                log.warning("Trigger %r raised an exception", name, exc_info=True)
        return fired

    @property
    def registered(self) -> list[str]:
        return list(self._triggers)


# ── Module-level singleton ────────────────────────────────────────────────────

trigger_registry = TriggerRegistry()

# ── Built-in triggers (core-provided) ────────────────────────────────────────

trigger_registry.register(
    "escalation_critical",
    lambda e: (
        e.get("record_type") == "EscalationRecord"
        and str(e.get("trigger", "")).endswith("critical_invariant_violation")
    ),
)

trigger_registry.register(
    "escalation_severe",
    lambda e: (
        e.get("record_type") == "EscalationRecord"
        and e.get("target_role") in ("meta_authority", "admin")
    ),
)
