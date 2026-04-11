"""Tests for parallel authority tracks — domain authority isolation.

Verifies:
- DA tokens are domain-scoped (iss: lumina-domain, token_scope: domain)
- DA tokens are rejected by admin endpoints (and vice versa)
- DA tokens are rejected by user endpoints (and vice versa)
- governed_modules boundary enforcement in permissions
- No escalation path from domain track to system track
- Domain middleware enforces scope correctly
"""

from __future__ import annotations

import pytest

from lumina.auth import auth
from lumina.auth.auth import (
    ADMIN_JWT_ISSUER,
    ADMIN_ROLES,
    DOMAIN_AUTHORITY_ROLES,
    DOMAIN_JWT_ISSUER,
    USER_JWT_ISSUER,
    USER_ROLES,
    TokenInvalidError,
    create_scoped_jwt,
    verify_scoped_jwt,
)
from lumina.core.permissions import Operation, check_permission


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _configure_secrets(monkeypatch):
    """Set up separate admin/domain/user/legacy secrets for each test."""
    monkeypatch.setattr(auth, "JWT_SECRET", "legacy-secret-for-tests")
    monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "admin-secret-for-tests")
    monkeypatch.setattr(auth, "DOMAIN_JWT_SECRET", "domain-secret-for-tests")
    monkeypatch.setattr(auth, "USER_JWT_SECRET", "user-secret-for-tests")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")


# ── DA token scope assignment ─────────────────────────────────


class TestDomainAuthorityTokenScope:
    def test_da_gets_domain_scope(self):
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"

    def test_da_gets_domain_issuer(self):
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        payload = verify_scoped_jwt(token)
        assert payload["iss"] == DOMAIN_JWT_ISSUER

    def test_da_not_in_admin_roles(self):
        assert "domain_authority" not in ADMIN_ROLES

    def test_da_not_in_user_roles(self):
        assert "domain_authority" not in USER_ROLES

    def test_da_in_domain_authority_roles(self):
        assert "domain_authority" in DOMAIN_AUTHORITY_ROLES

    def test_da_governed_modules_in_token(self):
        modules = ["domain/edu/algebra/v1", "domain/edu/geometry/v1"]
        token = create_scoped_jwt(
            user_id="da1", role="domain_authority", governed_modules=modules,
        )
        payload = verify_scoped_jwt(token)
        assert payload["governed_modules"] == modules


# ── Cross-track rejection ─────────────────────────────────────


class TestCrossTrackRejection:
    def test_da_token_rejected_by_admin_scope(self):
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="admin")

    def test_da_token_rejected_by_user_scope(self):
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="user")

    def test_admin_token_rejected_by_domain_scope(self):
        token = create_scoped_jwt(user_id="root1", role="root")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="domain")

    def test_user_token_rejected_by_domain_scope(self):
        token = create_scoped_jwt(user_id="u1", role="user")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="domain")

    def test_it_support_token_rejected_by_domain_scope(self):
        token = create_scoped_jwt(user_id="it1", role="it_support")
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="domain")


# ── Signing secret isolation ──────────────────────────────────


class TestSigningSecretIsolation:
    def test_da_token_signed_with_domain_secret(self, monkeypatch):
        """DA token cannot be verified after domain secret changes."""
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        monkeypatch.setattr(auth, "DOMAIN_JWT_SECRET", "rotated-domain-secret")
        with pytest.raises(TokenInvalidError, match="Signature"):
            verify_scoped_jwt(token)

    def test_da_token_unaffected_by_admin_secret_rotation(self, monkeypatch):
        """Rotating admin secret does not break existing DA tokens."""
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        monkeypatch.setattr(auth, "ADMIN_JWT_SECRET", "rotated-admin-secret")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"

    def test_da_token_unaffected_by_user_secret_rotation(self, monkeypatch):
        """Rotating user secret does not break existing DA tokens."""
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        monkeypatch.setattr(auth, "USER_JWT_SECRET", "rotated-user-secret")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"

    def test_domain_secret_fallback_to_legacy(self, monkeypatch):
        """If DOMAIN_JWT_SECRET is empty, falls back to JWT_SECRET."""
        monkeypatch.setattr(auth, "DOMAIN_JWT_SECRET", "")
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"


# ── governed_modules permission boundary ──────────────────────


class TestGovernedModulesBoundary:
    """Test that DA permissions are clamped to governed_modules."""

    def _make_perms(self, mode="750", owner="da1"):
        return {"mode": mode, "owner": owner, "group": "educators"}

    def test_da_allowed_inside_governed_module(self):
        result = check_permission(
            user_id="da1",
            user_role="domain_authority",
            module_permissions=self._make_perms(),
            operation=Operation.READ,
            governed_modules=["domain/edu/algebra/v1"],
            module_id="domain/edu/algebra/v1",
        )
        assert result is True

    def test_da_denied_outside_governed_module(self):
        result = check_permission(
            user_id="da1",
            user_role="domain_authority",
            module_permissions=self._make_perms(),
            operation=Operation.READ,
            governed_modules=["domain/edu/algebra/v1"],
            module_id="domain/edu/geometry/v1",
        )
        assert result is False

    def test_da_denied_when_governed_modules_empty(self):
        result = check_permission(
            user_id="da1",
            user_role="domain_authority",
            module_permissions=self._make_perms(),
            operation=Operation.READ,
            governed_modules=[],
            module_id="domain/edu/algebra/v1",
        )
        assert result is False

    def test_root_not_affected_by_governed_modules(self):
        """Root bypasses all permission checks regardless of governed_modules."""
        result = check_permission(
            user_id="root1",
            user_role="root",
            module_permissions=self._make_perms(),
            operation=Operation.READ,
            governed_modules=[],
            module_id="domain/edu/algebra/v1",
        )
        assert result is True

    def test_da_multiple_governed_modules(self):
        modules = ["domain/edu/algebra/v1", "domain/edu/geometry/v1"]
        for mod in modules:
            result = check_permission(
                user_id="da1",
                user_role="domain_authority",
                module_permissions=self._make_perms(),
                operation=Operation.READ,
                governed_modules=modules,
                module_id=mod,
            )
            assert result is True, f"DA should have access to governed module {mod}"


# ── No escalation path ───────────────────────────────────────


class TestNoEscalationPath:
    def test_da_cannot_mint_admin_token(self):
        """create_scoped_jwt always routes DA to domain scope."""
        token = create_scoped_jwt(user_id="da1", role="domain_authority")
        payload = verify_scoped_jwt(token)
        assert payload["token_scope"] == "domain"
        assert payload["iss"] == DOMAIN_JWT_ISSUER
        # Even if we try to verify as admin, it fails
        with pytest.raises(TokenInvalidError, match="scope mismatch"):
            verify_scoped_jwt(token, required_scope="admin")

    def test_all_three_tracks_use_different_issuers(self):
        admin_token = create_scoped_jwt(user_id="u", role="root")
        domain_token = create_scoped_jwt(user_id="u", role="domain_authority")
        user_token = create_scoped_jwt(user_id="u", role="user")

        admin_p = verify_scoped_jwt(admin_token)
        domain_p = verify_scoped_jwt(domain_token)
        user_p = verify_scoped_jwt(user_token)

        issuers = {admin_p["iss"], domain_p["iss"], user_p["iss"]}
        assert len(issuers) == 3
        assert issuers == {ADMIN_JWT_ISSUER, DOMAIN_JWT_ISSUER, USER_JWT_ISSUER}

    def test_all_three_tracks_use_different_scopes(self):
        admin_token = create_scoped_jwt(user_id="u", role="root")
        domain_token = create_scoped_jwt(user_id="u", role="domain_authority")
        user_token = create_scoped_jwt(user_id="u", role="user")

        scopes = {
            verify_scoped_jwt(admin_token)["token_scope"],
            verify_scoped_jwt(domain_token)["token_scope"],
            verify_scoped_jwt(user_token)["token_scope"],
        }
        assert scopes == {"admin", "domain", "user"}
