"""Tests for the Hierarchical TTL Manager."""

from __future__ import annotations

import pytest

from lumina.core.ttl_manager import (
    DEFAULT_DOMAIN_TTL,
    DEFAULT_MODULE_TTL,
    DEFAULT_SYSTEM_TTL,
    TTLEntry,
    TTLManager,
    Tier,
)


# ── Helpers ───────────────────────────────────────────────────

class FakeClock:
    """Deterministic clock for testing TTL expiry."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ══════════════════════════════════════════════════════════════
#  Tier enum
# ══════════════════════════════════════════════════════════════


class TestTier:
    def test_from_string(self):
        assert Tier("module") is Tier.MODULE
        assert Tier("domain") is Tier.DOMAIN
        assert Tier("system") is Tier.SYSTEM

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            Tier("invalid")


# ══════════════════════════════════════════════════════════════
#  TTLManager — defaults
# ══════════════════════════════════════════════════════════════


class TestTTLManagerDefaults:
    def test_default_ttls(self):
        mgr = TTLManager()
        assert mgr.get_ttl(Tier.MODULE) == DEFAULT_MODULE_TTL
        assert mgr.get_ttl(Tier.DOMAIN) == DEFAULT_DOMAIN_TTL
        assert mgr.get_ttl(Tier.SYSTEM) == DEFAULT_SYSTEM_TTL

    def test_hierarchy_order(self):
        """Module < domain < system."""
        mgr = TTLManager()
        assert mgr.get_ttl(Tier.MODULE) < mgr.get_ttl(Tier.DOMAIN) < mgr.get_ttl(Tier.SYSTEM)


# ══════════════════════════════════════════════════════════════
#  TTLManager — from_temporal_policy factory
# ══════════════════════════════════════════════════════════════


class TestFromTemporalPolicy:
    def test_custom_values(self):
        policy = {
            "module_ttl_seconds": 120,
            "domain_ttl_seconds": 3600,
            "system_ttl_seconds": 7200,
        }
        mgr = TTLManager.from_temporal_policy(policy)
        assert mgr.get_ttl(Tier.MODULE) == 120
        assert mgr.get_ttl(Tier.DOMAIN) == 3600
        assert mgr.get_ttl(Tier.SYSTEM) == 7200

    def test_partial_override(self):
        policy = {"module_ttl_seconds": 60}
        mgr = TTLManager.from_temporal_policy(policy)
        assert mgr.get_ttl(Tier.MODULE) == 60
        assert mgr.get_ttl(Tier.DOMAIN) == DEFAULT_DOMAIN_TTL  # fallback

    def test_none_policy_uses_defaults(self):
        mgr = TTLManager.from_temporal_policy(None)
        assert mgr.get_ttl(Tier.MODULE) == DEFAULT_MODULE_TTL

    def test_empty_policy_uses_defaults(self):
        mgr = TTLManager.from_temporal_policy({})
        assert mgr.get_ttl(Tier.SYSTEM) == DEFAULT_SYSTEM_TTL


# ══════════════════════════════════════════════════════════════
#  Register / touch / retrieve
# ══════════════════════════════════════════════════════════════


class TestRegisterAndTouch:
    def test_register_creates_entry(self):
        clock = FakeClock(100.0)
        mgr = TTLManager(clock=clock)
        entry = mgr.register(Tier.MODULE, "step:42")
        assert entry.tier is Tier.MODULE
        assert entry.key == "step:42"
        assert entry.last_touched == 100.0
        assert mgr.size == 1

    def test_register_overwrites(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(clock=clock)
        mgr.register(Tier.MODULE, "k")
        clock.advance(5)
        mgr.register(Tier.MODULE, "k")
        assert mgr.size == 1
        assert mgr.get("k").last_touched == 5.0

    def test_touch_updates_timestamp(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(clock=clock)
        mgr.register(Tier.DOMAIN, "ctx:edu")
        clock.advance(10)
        mgr.touch(Tier.DOMAIN, "ctx:edu")
        assert mgr.get("ctx:edu").last_touched == 10.0

    def test_touch_auto_registers(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(clock=clock)
        entry = mgr.touch(Tier.SYSTEM, "new-key")
        assert entry is not None
        assert mgr.size == 1

    def test_register_with_string_tier(self):
        mgr = TTLManager()
        entry = mgr.register("module", "k")
        assert entry.tier is Tier.MODULE

    def test_keys(self):
        mgr = TTLManager()
        mgr.register(Tier.MODULE, "a")
        mgr.register(Tier.DOMAIN, "b")
        assert sorted(mgr.keys()) == ["a", "b"]


# ══════════════════════════════════════════════════════════════
#  Prune
# ══════════════════════════════════════════════════════════════


class TestPrune:
    def test_nothing_to_prune(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(clock=clock)
        mgr.register(Tier.MODULE, "k")
        assert mgr.prune() == []
        assert mgr.size == 1

    def test_module_expires_before_domain(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(
            ttl_config={Tier.MODULE: 100, Tier.DOMAIN: 1000},
            clock=clock,
        )
        mgr.register(Tier.MODULE, "mod-entry")
        mgr.register(Tier.DOMAIN, "dom-entry")

        clock.advance(101)  # past module TTL, within domain TTL
        pruned = mgr.prune()
        pruned_keys = [e.key for e in pruned]
        assert "mod-entry" in pruned_keys
        assert "dom-entry" not in pruned_keys
        assert mgr.size == 1

    def test_all_tiers_expire(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(
            ttl_config={Tier.MODULE: 10, Tier.DOMAIN: 20, Tier.SYSTEM: 30},
            clock=clock,
        )
        mgr.register(Tier.MODULE, "m")
        mgr.register(Tier.DOMAIN, "d")
        mgr.register(Tier.SYSTEM, "s")

        clock.advance(31)
        pruned = mgr.prune()
        assert len(pruned) == 3
        assert mgr.size == 0

    def test_touch_prevents_expiry(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(ttl_config={Tier.MODULE: 100}, clock=clock)
        mgr.register(Tier.MODULE, "k")
        clock.advance(80)
        mgr.touch(Tier.MODULE, "k")  # reset to 80
        clock.advance(80)  # now at 160, but last_touched was 80 → age=80 ≤ 100
        assert mgr.prune() == []

    def test_prune_removes_from_store(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(ttl_config={Tier.MODULE: 10}, clock=clock)
        mgr.register(Tier.MODULE, "k")
        clock.advance(11)
        mgr.prune()
        assert mgr.get("k") is None


# ══════════════════════════════════════════════════════════════
#  is_alive
# ══════════════════════════════════════════════════════════════


class TestIsAlive:
    def test_alive_when_fresh(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(clock=clock)
        mgr.register(Tier.MODULE, "k")
        assert mgr.is_alive("k") is True

    def test_not_alive_after_ttl(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(ttl_config={Tier.MODULE: 10}, clock=clock)
        mgr.register(Tier.MODULE, "k")
        clock.advance(11)
        assert mgr.is_alive("k") is False

    def test_not_alive_when_missing(self):
        mgr = TTLManager()
        assert mgr.is_alive("nonexistent") is False

    def test_alive_at_exact_boundary(self):
        clock = FakeClock(0.0)
        mgr = TTLManager(ttl_config={Tier.MODULE: 10}, clock=clock)
        mgr.register(Tier.MODULE, "k")
        clock.advance(10)  # age == TTL → still alive (<=)
        assert mgr.is_alive("k") is True


# ══════════════════════════════════════════════════════════════
#  Metadata
# ══════════════════════════════════════════════════════════════


class TestMetadata:
    def test_register_with_metadata(self):
        mgr = TTLManager()
        entry = mgr.register(Tier.MODULE, "k", source="test", count=5)
        assert entry.metadata == {"source": "test", "count": 5}
