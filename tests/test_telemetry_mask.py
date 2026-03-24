"""Tests for lumina.system_log.telemetry_mask — field-level masking."""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os

import pytest

from lumina.system_log.event_payload import LogEvent, LogLevel, create_event
from lumina.system_log.telemetry_mask import (
    FieldRule,
    MaskingPolicy,
    Sensitivity,
    Strategy,
    apply_masking,
    get_active_policy,
    load_policy_from_dict,
    mask_event,
    set_active_policy,
    _path_matches,
)


# ── Helpers ────────────────────────────────────────────────────

def _make_event(**overrides) -> LogEvent:
    defaults = dict(
        source="test_module",
        level=LogLevel.INFO,
        category="test_cat",
        message="hello world",
        data={"user_id": "alice", "email": "alice@example.com", "score": 42},
    )
    defaults.update(overrides)
    return create_event(**defaults)


def _sha256(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _hmac_sha256(val: str, key: str) -> str:
    return hmac_mod.new(key.encode("utf-8"), val.encode("utf-8"), hashlib.sha256).hexdigest()


# ── Path matching ──────────────────────────────────────────────


class TestPathMatching:

    @pytest.mark.unit
    def test_exact_match(self) -> None:
        assert _path_matches("data.user_id", "data.user_id")

    @pytest.mark.unit
    def test_no_match(self) -> None:
        assert not _path_matches("data.user_id", "data.email")

    @pytest.mark.unit
    def test_single_wildcard(self) -> None:
        assert _path_matches("data.*", "data.user_id")
        assert _path_matches("data.*", "data.email")
        assert not _path_matches("data.*", "data.nested.field")

    @pytest.mark.unit
    def test_double_wildcard(self) -> None:
        assert _path_matches("data.**", "data.user_id")
        assert _path_matches("data.**", "data.nested.field")
        assert _path_matches("data.**.email", "data.nested.deep.email")

    @pytest.mark.unit
    def test_top_level(self) -> None:
        assert _path_matches("source", "source")
        assert not _path_matches("source", "message")


# ── Strategy implementations ───────────────────────────────────


class TestStrategies:

    @pytest.mark.unit
    def test_sha256_hash(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.SHA256_HASH),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["user_id"] == _sha256("alice")
        # Other fields unchanged
        assert masked.data["email"] == "alice@example.com"
        assert masked.data["score"] == 42

    @pytest.mark.unit
    def test_hmac_pseudonym_with_key(self, monkeypatch) -> None:
        monkeypatch.setenv("LUMINA_TELEMETRY_HMAC_KEY", "test-secret")
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.HMAC_PSEUDONYM),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["user_id"] == _hmac_sha256("alice", "test-secret")

    @pytest.mark.unit
    def test_hmac_fallback_to_sha256_without_key(self, monkeypatch) -> None:
        monkeypatch.delenv("LUMINA_TELEMETRY_HMAC_KEY", raising=False)
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.HMAC_PSEUDONYM),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["user_id"] == _sha256("alice")

    @pytest.mark.unit
    def test_redact(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.email", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["email"] == "[REDACTED]"

    @pytest.mark.unit
    def test_truncate(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.email", sensitivity=Sensitivity.CONFIDENTIAL, strategy=Strategy.TRUNCATE, truncate_length=5),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["email"] == "alice…"

    @pytest.mark.unit
    def test_truncate_short_value_unchanged(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.CONFIDENTIAL, strategy=Strategy.TRUNCATE, truncate_length=100),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["user_id"] == "alice"

    @pytest.mark.unit
    def test_pass_strategy(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.PUBLIC, strategy=Strategy.PASS),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["user_id"] == "alice"


# ── Nested data ────────────────────────────────────────────────


class TestNestedData:

    @pytest.mark.unit
    def test_nested_field_masking(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.profile.email", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ])
        evt = _make_event(data={"profile": {"email": "bob@example.com", "name": "Bob"}})
        masked = mask_event(evt, policy)
        assert masked.data["profile"]["email"] == "[REDACTED]"
        assert masked.data["profile"]["name"] == "Bob"

    @pytest.mark.unit
    def test_wildcard_across_nested(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.**.secret", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ])
        evt = _make_event(data={"level1": {"level2": {"secret": "s3cr3t", "public": "ok"}}})
        masked = mask_event(evt, policy)
        assert masked.data["level1"]["level2"]["secret"] == "[REDACTED]"
        assert masked.data["level1"]["level2"]["public"] == "ok"


# ── Top-level field masking ────────────────────────────────────


class TestTopLevelFields:

    @pytest.mark.unit
    def test_mask_source(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="source", sensitivity=Sensitivity.INTERNAL, strategy=Strategy.SHA256_HASH),
        ])
        evt = _make_event(source="sensitive_module")
        masked = mask_event(evt, policy)
        assert masked.source == _sha256("sensitive_module")

    @pytest.mark.unit
    def test_mask_message(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="message", sensitivity=Sensitivity.CONFIDENTIAL, strategy=Strategy.REDACT),
        ])
        evt = _make_event(message="User alice logged in")
        masked = mask_event(evt, policy)
        assert masked.message == "[REDACTED]"

    @pytest.mark.unit
    def test_timestamp_and_level_never_masked(self) -> None:
        """Timestamp and level are structural — they must never be masked."""
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.*", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.timestamp == evt.timestamp
        assert masked.level == evt.level


# ── Record integrity ───────────────────────────────────────────


class TestRecordIntegrity:

    @pytest.mark.unit
    def test_record_field_never_masked(self) -> None:
        """The hash-chained record must pass through untouched."""
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.*", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ])
        record = {"type": "CommitmentRecord", "hash": "abc123", "prev_hash": "genesis"}
        evt = _make_event(data={"user_id": "alice"})
        # Manually construct with record
        evt_with_record = LogEvent(
            timestamp=evt.timestamp,
            source=evt.source,
            level=LogLevel.AUDIT,
            category="audit",
            message="commit",
            data={"user_id": "alice"},
            record=record,
        )
        masked = mask_event(evt_with_record, policy)
        assert masked.record is record  # exact same object — untouched
        assert masked.data["user_id"] == "[REDACTED]"


# ── Default strategy ───────────────────────────────────────────


class TestDefaultStrategy:

    @pytest.mark.unit
    def test_default_redact_all_unmatched(self) -> None:
        policy = MaskingPolicy(
            rules=[
                FieldRule(path="data.safe", sensitivity=Sensitivity.PUBLIC, strategy=Strategy.PASS),
            ],
            default_strategy=Strategy.REDACT,
        )
        evt = _make_event(data={"safe": "ok", "sensitive": "secret"})
        masked = mask_event(evt, policy)
        assert masked.data["safe"] == "ok"
        assert masked.data["sensitive"] == "[REDACTED]"


# ── Policy loading from dict ──────────────────────────────────


class TestPolicyLoading:

    @pytest.mark.unit
    def test_load_policy_from_dict(self) -> None:
        raw = {
            "schema_id": "lumina:telemetry-masking:v1",
            "version": "1.0.0",
            "fields": [
                {"path": "data.user_id", "sensitivity": "restricted", "strategy": "sha256_hash"},
                {"path": "data.email", "sensitivity": "restricted", "strategy": "redact"},
                {"path": "data.name", "sensitivity": "confidential", "strategy": "truncate", "truncate_length": 3},
            ],
            "default_strategy": "pass",
        }
        policy = load_policy_from_dict(raw)
        assert len(policy.rules) == 3
        assert policy.rules[0].strategy == Strategy.SHA256_HASH
        assert policy.rules[1].strategy == Strategy.REDACT
        assert policy.rules[2].truncate_length == 3
        assert policy.default_strategy == Strategy.PASS


# ── Active policy & apply_masking ─────────────────────────────


class TestApplyMasking:

    @pytest.mark.unit
    def test_no_op_when_disabled(self, monkeypatch) -> None:
        monkeypatch.setenv("LUMINA_TELEMETRY_MASKING_ENABLED", "false")
        set_active_policy(MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ]))
        evt = _make_event()
        result = apply_masking(evt)
        assert result.data["user_id"] == "alice"  # not masked
        set_active_policy(None)

    @pytest.mark.unit
    def test_masks_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("LUMINA_TELEMETRY_MASKING_ENABLED", "true")
        set_active_policy(MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ]))
        evt = _make_event()
        result = apply_masking(evt)
        assert result.data["user_id"] == "[REDACTED]"
        set_active_policy(None)

    @pytest.mark.unit
    def test_no_op_when_no_policy(self, monkeypatch) -> None:
        monkeypatch.setenv("LUMINA_TELEMETRY_MASKING_ENABLED", "true")
        set_active_policy(None)
        evt = _make_event()
        result = apply_masking(evt)
        assert result.data["user_id"] == "alice"

    @pytest.mark.unit
    def test_set_and_get_policy(self) -> None:
        policy = MaskingPolicy(rules=[])
        set_active_policy(policy)
        assert get_active_policy() is policy
        set_active_policy(None)
        assert get_active_policy() is None


# ── Pure function guarantee ────────────────────────────────────


class TestPurity:

    @pytest.mark.unit
    def test_original_event_not_mutated(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
        ])
        evt = _make_event()
        original_user_id = evt.data["user_id"]
        masked = mask_event(evt, policy)
        assert evt.data["user_id"] == original_user_id
        assert masked.data["user_id"] == "[REDACTED]"
        assert masked is not evt

    @pytest.mark.unit
    def test_deterministic_sha256(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.SHA256_HASH),
        ])
        evt = _make_event()
        m1 = mask_event(evt, policy)
        m2 = mask_event(evt, policy)
        assert m1.data["user_id"] == m2.data["user_id"]

    @pytest.mark.unit
    def test_deterministic_hmac(self, monkeypatch) -> None:
        monkeypatch.setenv("LUMINA_TELEMETRY_HMAC_KEY", "key123")
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.HMAC_PSEUDONYM),
        ])
        evt = _make_event()
        m1 = mask_event(evt, policy)
        m2 = mask_event(evt, policy)
        assert m1.data["user_id"] == m2.data["user_id"]


# ── First-match-wins rule ordering ─────────────────────────────


class TestRuleOrdering:

    @pytest.mark.unit
    def test_first_match_wins(self) -> None:
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.user_id", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
            FieldRule(path="data.user_id", sensitivity=Sensitivity.INTERNAL, strategy=Strategy.SHA256_HASH),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        # First rule wins — redact, not hash
        assert masked.data["user_id"] == "[REDACTED]"

    @pytest.mark.unit
    def test_wildcard_vs_specific(self) -> None:
        """Specific rule before wildcard takes precedence."""
        policy = MaskingPolicy(rules=[
            FieldRule(path="data.email", sensitivity=Sensitivity.RESTRICTED, strategy=Strategy.REDACT),
            FieldRule(path="data.*", sensitivity=Sensitivity.INTERNAL, strategy=Strategy.SHA256_HASH),
        ])
        evt = _make_event()
        masked = mask_event(evt, policy)
        assert masked.data["email"] == "[REDACTED]"
        assert masked.data["user_id"] == _sha256("alice")
