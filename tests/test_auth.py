from __future__ import annotations

import time

import pytest

from lumina.auth import auth


@pytest.mark.unit
def test_hash_and_verify_password_roundtrip() -> None:
    stored = auth.hash_password("S3curePass!")
    assert ":" in stored
    assert auth.verify_password("S3curePass!", stored)
    assert not auth.verify_password("wrong-pass", stored)


@pytest.mark.unit
def test_verify_password_rejects_malformed_storage() -> None:
    assert not auth.verify_password("anything", "not-a-salt-hash")


@pytest.mark.unit
def test_create_and_verify_jwt_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    token = auth.create_jwt(user_id="u-123", role="user", governed_modules=["mod-1"], ttl_minutes=5)

    payload = auth.verify_jwt(token)
    assert payload["sub"] == "u-123"
    assert payload["role"] == "user"
    assert payload["governed_modules"] == ["mod-1"]
    assert payload["iss"] == auth.JWT_ISSUER


@pytest.mark.unit
def test_create_jwt_rejects_invalid_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    with pytest.raises(ValueError, match="Invalid role"):
        auth.create_jwt(user_id="u-1", role="superuser")


@pytest.mark.unit
def test_create_jwt_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "")
    with pytest.raises(auth.AuthError, match="LUMINA_JWT_SECRET must be set"):
        auth.create_jwt(user_id="u-1", role="user")


@pytest.mark.unit
def test_verify_jwt_rejects_tampered_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    token = auth.create_jwt(user_id="u-1", role="user")
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload[:-1]}A.{sig}"

    with pytest.raises(auth.TokenInvalidError):
        auth.verify_jwt(tampered)


@pytest.mark.unit
def test_verify_jwt_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    token = auth.create_jwt(user_id="u-1", role="user", ttl_minutes=0)
    time.sleep(1)

    with pytest.raises(auth.TokenExpiredError):
        auth.verify_jwt(token)


@pytest.mark.unit
def test_verify_jwt_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    token = auth.create_jwt(user_id="u-1", role="user")

    # Temporarily switch expected issuer to force mismatch.
    monkeypatch.setattr(auth, "JWT_ISSUER", "different-issuer")
    with pytest.raises(auth.TokenInvalidError, match="Unexpected issuer"):
        auth.verify_jwt(token)


@pytest.mark.unit
def test_verify_jwt_rejects_malformed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_SECRET", "test-secret")
    with pytest.raises(auth.TokenInvalidError, match="Malformed token"):
        auth.verify_jwt("not.a.valid.jwt.with.extra")
