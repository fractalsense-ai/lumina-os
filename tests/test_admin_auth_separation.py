"""Tests for Phase 6: Air-Gapped Admin Auth.

Verifies:
- Scoped JWT creation and verification
- Admin tokens rejected by user endpoints (and vice versa)
- Legacy tokens still work (migration compatibility)
- Admin middleware enforcement
- Admin auth route isolation
"""

from __future__ import annotations

import time

import pytest

from lumina.auth import auth
from lumina.auth.auth import (
    ADMIN_JWT_ISSUER,
    ADMIN_ROLES,
    DOMAIN_ADMIN_ROLES,
    DOMAIN_JWT_ISSUER,
    USER_JWT_ISSUER,
    USER_ROLES,
    AuthError,
    TokenExpiredError,
    TokenInvalidError,
    create_jwt,
    create_scoped_jwt,
    verify_jwt,
    verify_scoped_jwt,
)


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _configure_secrets(monkeypatch):
    """Set up separate admin/domain/user/legacy secrets for each test."""
    monkeypatch.setattr(auth, "JWT_SECRET", "legacy-secret-for-tests")
    monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "admin-secret-for-tests")
    monkeypatch.setattr(auth, "DOMAIN_JWT_SECRET", "domain-secret-for-tests")
    monkeypatch.setattr(auth, "USER_JWT_SECRET", "user-secret-for-tests")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")


# ── Scoped JWT creation ──────────────────────────────────────


class TestCreateScopedJwt:
    def test_admin_role_gets_admin_scope(self):
        token = create_scoped_jwt(user_id="u1", role="root")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "admin"
        assert payload["iss"] == ADMIN_JWT_ISSUER

    def test_domain_admin_gets_domain_scope(self):
        token = create_scoped_jwt(user_id="u2", role="admin")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"
        assert payload["iss"] == DOMAIN_JWT_ISSUER

    def test_super_admin_gets_admin_scope(self):
        token = create_scoped_jwt(user_id="u3", role="super_admin")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "admin"

    def test_user_role_gets_user_scope(self):
        token = create_scoped_jwt(user_id="u4", role="user")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "user"
        assert payload["iss"] == USER_JWT_ISSUER

    def test_operator_gets_user_scope(self):
        token = create_scoped_jwt(user_id="u5", role="operator")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "user"

    def test_half_operator_gets_user_scope(self):
        token = create_scoped_jwt(user_id="u6", role="half_operator")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "user"

    def test_guest_gets_user_scope(self):
        token = create_scoped_jwt(user_id="u7", role="guest")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "user"

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError, match="Invalid role"):
            create_scoped_jwt(user_id="u8", role="nonexistent")

    def test_all_admin_roles_covered(self):
        for role in ADMIN_ROLES:
            token = create_scoped_jwt(user_id="u", role=role)
            payload = verify_scoped_jwt(token)
            assert payload["token_scope"] == "admin"

    def test_all_user_roles_covered(self):
        for role in USER_ROLES:
            token = create_scoped_jwt(user_id="u", role=role)
            payload = verify_scoped_jwt(token)
            assert payload["token_scope"] == "user"

    def test_governed_modules_persisted(self):
        token = create_scoped_jwt(user_id="u", role="admin", governed_modules=["m1"])
        payload = verify_scoped_jwt(token)
        assert payload["governed_modules"] == ["m1"]

    def test_domain_roles_persisted(self):
        dr = {"domain/edu/algebra/v1": "ta"}
        token = create_scoped_jwt(user_id="u", role="root", domain_roles=dr)
        payload = verify_scoped_jwt(token)
        assert payload["domain_roles"] == dr

    def test_ttl_override(self):
        token = create_scoped_jwt(user_id="u", role="root", ttl_minutes=5)
        payload = verify_scoped_jwt(token)
        assert payload["exp"] - payload["iat"] == 300


# ── Scoped JWT verification ──────────────────────────────────


class TestVerifyScopedJwt:
    def test_admin_token_verified_with_admin_secret(self):
        token = create_scoped_jwt(user_id="u", role="root")
        payload = verify_scoped_jwt(token, required_scope="admin")
        assert payload["sub"] == "u"
        assert payload["role"] == "root"

    def test_user_token_verified_with_user_secret(self):
        token = create_scoped_jwt(user_id="u", role="user")
        payload = verify_scoped_jwt(token, required_scope="user")
        assert payload["sub"] == "u"

    def test_admin_token_rejected_by_user_scope(self):
        token = create_scoped_jwt(user_id="u", role="root")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="user")

    def test_user_token_rejected_by_admin_scope(self):
        token = create_scoped_jwt(user_id="u", role="user")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="admin")

    def test_expired_token_raises(self):
        token = create_scoped_jwt(user_id="u", role="root", ttl_minutes=-1)
        with pytest.raises(TokenExpiredError):
            verify_scoped_jwt(token)

    def test_malformed_token_raises(self):
        with pytest.raises(TokenInvalidError, match="Malformed"):
            verify_scoped_jwt("not.a.valid.token.at.all")

    def test_wrong_secret_rejects(self, monkeypatch):
        token = create_scoped_jwt(user_id="u", role="root")
        monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "different-secret")
        with pytest.raises(TokenInvalidError, match="Signature"):
            verify_scoped_jwt(token)

    def test_revoked_token_rejected(self):
        token = create_scoped_jwt(user_id="u", role="root")
        payload = verify_scoped_jwt(token)
        auth.revoke_token_jti(payload["jti"])
        with pytest.raises(TokenInvalidError, match="revoked"):
            verify_scoped_jwt(token)

    def test_no_required_scope_accepts_any(self):
        admin_token = create_scoped_jwt(user_id="u", role="root")
        user_token = create_scoped_jwt(user_id="u", role="user")
        assert verify_scoped_jwt(admin_token)["token_scope"] == "admin"
        assert verify_scoped_jwt(user_token)["token_scope"] == "user"


# ── Legacy token backward compatibility ───────────────────────


class TestLegacyTokenMigration:
    def test_legacy_token_accepted_by_verify_scoped(self):
        """Legacy tokens (iss: lumina) should still work."""
        token = create_jwt(user_id="u", role="root")
        payload = verify_scoped_jwt(token)
        assert payload["sub"] == "u"
        # Scope inferred from role
        assert payload["token_scope"] == "admin"

    def test_legacy_user_token_inferred_as_user_scope(self):
        token = create_jwt(user_id="u", role="user")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "user"

    def test_legacy_token_still_works_with_verify_jwt(self):
        """Existing verify_jwt() path is completely untouched."""
        token = create_jwt(user_id="u", role="root")
        payload = verify_jwt(token)
        assert payload["sub"] == "u"
        assert payload["iss"] == "lumina"

    def test_legacy_admin_rejected_when_user_scope_required(self):
        token = create_jwt(user_id="u", role="root")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="user")

    def test_legacy_user_rejected_when_admin_scope_required(self):
        token = create_jwt(user_id="u", role="user")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="admin")


# ── Fallback when scoped secrets not set ──────────────────────


class TestSecretFallback:
    def test_no_admin_secret_falls_back_to_jwt_secret(self, monkeypatch):
        monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "")
        token = create_scoped_jwt(user_id="u", role="root")
        # Should verify against JWT_SECRET fallback
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "admin"

    def test_no_domain_secret_falls_back_to_jwt_secret(self, monkeypatch):
        monkeypatch.setattr(auth, "DOMAIN_JWT_SECRET", "")
        token = create_scoped_jwt(user_id="u", role="admin")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"

    def test_no_user_secret_falls_back_to_jwt_secret(self, monkeypatch):
        monkeypatch.setattr(auth, "USER_JWT_SECRET", "")
        token = create_scoped_jwt(user_id="u", role="user")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "user"

    def test_all_secrets_empty_raises(self, monkeypatch):
        monkeypatch.setattr(auth, "JWT_SECRET", "")
        monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "")
        monkeypatch.setattr(auth, "USER_JWT_SECRET", "")
        with pytest.raises(AuthError):
            create_scoped_jwt(user_id="u", role="root")


# ── Cross-scope isolation ─────────────────────────────────────


class TestCrossScopeIsolation:
    def test_admin_token_cannot_be_verified_with_user_secret(self, monkeypatch):
        """Even without scope enforcement, different secrets prevent cross-use."""
        token = create_scoped_jwt(user_id="u", role="root")
        # Swap admin and user secrets
        monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "user-secret-for-tests")
        monkeypatch.setattr(auth, "USER_JWT_SECRET", "admin-secret-for-tests")
        # The token was signed with the original admin secret, which is now
        # the user secret — but verify_scoped_jwt reads iss first, so it
        # picks the new admin secret → signature mismatch
        with pytest.raises(TokenInvalidError, match="Signature"):
            verify_scoped_jwt(token)


# ── Admin middleware unit tests ───────────────────────────────


class TestAdminMiddleware:
    def test_require_admin_auth_passes_admin_user(self):
        from lumina.api.admin_middleware import require_admin_auth
        user = {"sub": "u1", "role": "root", "token_scope": "admin"}
        assert require_admin_auth(user) is user

    def test_require_admin_auth_rejects_none(self):
        from lumina.api.admin_middleware import require_admin_auth
        with pytest.raises(Exception):  # HTTPException
            require_admin_auth(None)

    def test_require_admin_auth_rejects_user_scope(self):
        from lumina.api.admin_middleware import require_admin_auth
        user = {"sub": "u1", "role": "user", "token_scope": "user"}
        with pytest.raises(Exception):  # HTTPException 403
            require_admin_auth(user)

    def test_require_user_auth_passes_user(self):
        from lumina.api.admin_middleware import require_user_auth
        user = {"sub": "u1", "role": "user", "token_scope": "user"}
        assert require_user_auth(user) is user

    def test_require_user_auth_rejects_admin(self):
        from lumina.api.admin_middleware import require_user_auth
        user = {"sub": "u1", "role": "root", "token_scope": "admin"}
        with pytest.raises(Exception):  # HTTPException 403
            require_user_auth(user)

    def test_require_user_auth_rejects_none(self):
        from lumina.api.admin_middleware import require_user_auth
        with pytest.raises(Exception):  # HTTPException
            require_user_auth(None)


# ── Role classification constants ─────────────────────────────


class TestRoleConstants:
    def test_admin_roles_are_subset_of_valid_roles(self):
        from lumina.auth.auth import VALID_ROLES
        assert ADMIN_ROLES <= VALID_ROLES

    def test_user_roles_are_subset_of_valid_roles(self):
        from lumina.auth.auth import VALID_ROLES
        assert USER_ROLES <= VALID_ROLES

    def test_domain_roles_are_subset_of_valid_roles(self):
        from lumina.auth.auth import VALID_ROLES
        assert DOMAIN_ADMIN_ROLES <= VALID_ROLES

    def test_admin_and_user_roles_are_disjoint(self):
        assert ADMIN_ROLES & USER_ROLES == frozenset()

    def test_admin_and_domain_roles_are_disjoint(self):
        assert ADMIN_ROLES & DOMAIN_ADMIN_ROLES == frozenset()

    def test_user_and_domain_roles_are_disjoint(self):
        assert USER_ROLES & DOMAIN_ADMIN_ROLES == frozenset()

    def test_all_three_tracks_cover_all_roles(self):
        from lumina.auth.auth import VALID_ROLES
        assert ADMIN_ROLES | DOMAIN_ADMIN_ROLES | USER_ROLES == VALID_ROLES
