"""Tests for transcript HMAC seal — sign/verify, key isolation, tamper detection."""

from __future__ import annotations

import os
import pytest

# Ensure a JWT secret is available for the auth module
os.environ.setdefault("LUMINA_JWT_SECRET", "test-secret-for-transcript-seal-012345678901234567890")


from lumina.auth.auth import (
    derive_transcript_key,
    sign_transcript,
    verify_transcript,
)


# ── HKDF key derivation ─────────────────────────────────────


def test_derive_transcript_key_returns_32_bytes():
    key = derive_transcript_key("user-001")
    assert isinstance(key, bytes)
    assert len(key) == 32


def test_derive_transcript_key_deterministic():
    k1 = derive_transcript_key("user-001")
    k2 = derive_transcript_key("user-001")
    assert k1 == k2


def test_derive_transcript_key_user_isolation():
    k1 = derive_transcript_key("user-001")
    k2 = derive_transcript_key("user-002")
    assert k1 != k2


# ── Sign / verify round trip ────────────────────────────────


def _sample_payload() -> dict:
    return {
        "transcript": [
            {"turn": 1, "user": "hello", "assistant": "Hi there", "ts": 1.0, "domain_id": "d1"},
            {"turn": 2, "user": "what is 2+2", "assistant": "4", "ts": 2.0, "domain_id": "d1"},
        ],
        "metadata": {
            "domain_id": "d1",
            "turn_count": 2,
            "last_activity_utc": 2.0,
        },
    }


def test_sign_verify_round_trip():
    payload = _sample_payload()
    sig = sign_transcript("user-001", payload)
    assert isinstance(sig, str)
    assert len(sig) == 64  # hex SHA-256
    assert verify_transcript("user-001", payload, sig)


def test_verify_rejects_wrong_user():
    payload = _sample_payload()
    sig = sign_transcript("user-001", payload)
    assert not verify_transcript("user-002", payload, sig)


def test_verify_rejects_tampered_transcript():
    payload = _sample_payload()
    sig = sign_transcript("user-001", payload)
    # Tamper with one character in the assistant response
    payload["transcript"][0]["assistant"] = "Hi there!"
    assert not verify_transcript("user-001", payload, sig)


def test_verify_rejects_tampered_metadata():
    payload = _sample_payload()
    sig = sign_transcript("user-001", payload)
    payload["metadata"]["turn_count"] = 999
    assert not verify_transcript("user-001", payload, sig)


def test_verify_rejects_garbage_signature():
    payload = _sample_payload()
    assert not verify_transcript("user-001", payload, "0" * 64)


def test_verify_rejects_truncated_signature():
    payload = _sample_payload()
    sig = sign_transcript("user-001", payload)
    assert not verify_transcript("user-001", payload, sig[:32])


# ── Canonical JSON determinism ───────────────────────────────


def test_key_order_irrelevant():
    """The seal must be the same regardless of dict insertion order."""
    p1 = {
        "transcript": [{"turn": 1, "user": "a", "assistant": "b", "ts": 0, "domain_id": "d"}],
        "metadata": {"domain_id": "d", "turn_count": 1, "last_activity_utc": 0},
    }
    p2 = {
        "metadata": {"turn_count": 1, "last_activity_utc": 0, "domain_id": "d"},
        "transcript": [{"domain_id": "d", "assistant": "b", "user": "a", "turn": 1, "ts": 0}],
    }
    s1 = sign_transcript("u", p1)
    s2 = sign_transcript("u", p2)
    assert s1 == s2


# ── Custom transcript secret ────────────────────────────────


def test_custom_transcript_secret(monkeypatch):
    """When LUMINA_TRANSCRIPT_HMAC_SECRET is set, it takes precedence."""
    import lumina.auth.auth as _auth

    original = _auth.TRANSCRIPT_HMAC_SECRET
    monkeypatch.setattr(_auth, "TRANSCRIPT_HMAC_SECRET", "custom-transcript-secret-1234567890")

    payload = _sample_payload()
    sig = sign_transcript("user-001", payload)

    # Must verify with the same secret
    assert verify_transcript("user-001", payload, sig)

    # Restore — a seal signed with the old secret must NOT verify
    monkeypatch.setattr(_auth, "TRANSCRIPT_HMAC_SECRET", original)
    assert not verify_transcript("user-001", payload, sig)
