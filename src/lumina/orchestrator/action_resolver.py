"""
action_resolver.py — Backward-compatibility shim.

The canonical implementation now lives in ``actor_resolver.py``.
This module re-exports ``ActorResolver`` under its former name
``ActionResolver`` so that existing imports continue to work.
"""

from lumina.orchestrator.actor_resolver import ActorResolver as ActionResolver  # noqa: F401
from lumina.orchestrator.actor_resolver import ActorResolver  # noqa: F401

__all__ = ["ActionResolver", "ActorResolver"]

