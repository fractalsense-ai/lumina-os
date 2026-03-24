"""ttl_manager.py — Hierarchical Time-To-Live context pruning.

Manages three TTL tiers (module < domain < system) inspired by CPU cache
levels.  Each registered entry has a *tier*, a *key*, and a *last_touched*
timestamp.  The :meth:`prune` method evicts entries whose age exceeds the
tier's TTL threshold.

Typical usage::

    mgr = TTLManager.from_temporal_policy(domain_physics.get("temporal_policy"))
    mgr.touch("module", "step_history:session-42")
    # ... later, on each request ...
    pruned = mgr.prune()
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("lumina-ttl")


# ── Tier enum ─────────────────────────────────────────────────

class Tier(str, Enum):
    MODULE = "module"
    DOMAIN = "domain"
    SYSTEM = "system"


# ── Defaults (seconds) ───────────────────────────────────────

DEFAULT_MODULE_TTL: int = 900       # 15 min
DEFAULT_DOMAIN_TTL: int = 14_400    # 4 h
DEFAULT_SYSTEM_TTL: int = 86_400    # 24 h

_TIER_DEFAULTS: dict[Tier, int] = {
    Tier.MODULE: DEFAULT_MODULE_TTL,
    Tier.DOMAIN: DEFAULT_DOMAIN_TTL,
    Tier.SYSTEM: DEFAULT_SYSTEM_TTL,
}


# ── Entry dataclass ───────────────────────────────────────────

@dataclass
class TTLEntry:
    tier: Tier
    key: str
    last_touched: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Manager ───────────────────────────────────────────────────

class TTLManager:
    """Hierarchical context TTL manager.

    Parameters
    ----------
    ttl_config:
        Mapping of ``Tier`` → TTL-in-seconds.  Missing tiers fall back to
        the defaults (900 / 14400 / 86400).
    clock:
        Callable returning the current monotonic time.  Override for testing.
    """

    def __init__(
        self,
        ttl_config: dict[Tier, int] | None = None,
        clock: Any = None,
    ) -> None:
        self._ttls: dict[Tier, int] = dict(_TIER_DEFAULTS)
        if ttl_config:
            self._ttls.update(ttl_config)
        self._clock = clock or time.monotonic
        self._entries: dict[str, TTLEntry] = {}

    # ── Factory ───────────────────────────────────────────────

    @classmethod
    def from_temporal_policy(
        cls,
        policy: dict[str, Any] | None = None,
        clock: Any = None,
    ) -> TTLManager:
        """Build from a ``temporal_policy`` dict (as in domain-physics)."""
        config: dict[Tier, int] = {}
        if policy:
            if "module_ttl_seconds" in policy:
                config[Tier.MODULE] = int(policy["module_ttl_seconds"])
            if "domain_ttl_seconds" in policy:
                config[Tier.DOMAIN] = int(policy["domain_ttl_seconds"])
            if "system_ttl_seconds" in policy:
                config[Tier.SYSTEM] = int(policy["system_ttl_seconds"])
        return cls(ttl_config=config, clock=clock)

    # ── Registration ──────────────────────────────────────────

    def register(self, tier: Tier | str, key: str, **metadata: Any) -> TTLEntry:
        """Register (or re-register) a context entry with a fresh timestamp."""
        tier = Tier(tier)
        entry = TTLEntry(
            tier=tier,
            key=key,
            last_touched=self._clock(),
            metadata=metadata,
        )
        self._entries[key] = entry
        return entry

    def touch(self, tier: Tier | str, key: str) -> TTLEntry | None:
        """Update the last_touched timestamp for an existing entry.

        If the key does not exist, registers it automatically.
        """
        entry = self._entries.get(key)
        if entry is None:
            return self.register(tier, key)
        entry.last_touched = self._clock()
        return entry

    # ── Pruning ───────────────────────────────────────────────

    def prune(self) -> list[TTLEntry]:
        """Remove all entries whose age exceeds their tier's TTL.

        Returns the list of pruned entries.
        """
        now = self._clock()
        expired: list[TTLEntry] = []
        for entry in list(self._entries.values()):
            ttl = self._ttls[entry.tier]
            if (now - entry.last_touched) > ttl:
                expired.append(entry)
        for entry in expired:
            del self._entries[entry.key]
        if expired:
            log.info(
                "TTL prune: removed %d entries (%s)",
                len(expired),
                ", ".join(e.key for e in expired),
            )
        return expired

    def is_alive(self, key: str) -> bool:
        """Check if an entry exists and has not exceeded its TTL."""
        entry = self._entries.get(key)
        if entry is None:
            return False
        ttl = self._ttls[entry.tier]
        return (self._clock() - entry.last_touched) <= ttl

    # ── Introspection ─────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> TTLEntry | None:
        return self._entries.get(key)

    def keys(self) -> list[str]:
        return list(self._entries.keys())

    def get_ttl(self, tier: Tier | str) -> int:
        return self._ttls[Tier(tier)]
