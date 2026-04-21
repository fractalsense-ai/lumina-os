"""Tests for zero-trust domain isolation in admin operations.

Validates that:
- can_govern_domain resolves domain names via registry when governed_modules
  contains module IDs (not domain names).
- list_users respects domain_id, module_id, and domain_role filters.
- Domain authorities are rejected when querying outside their scope.
- list_escalations enforces can_govern_domain boundary.
- _normalize_slm_command infers domain_id for list_users/list_escalations/
  list_modules from instruction text.
- Education NLP fallback injects domain_id: "education" automatically.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from lumina.system_log.admin_operations import can_govern_domain

REPO_ROOT = Path(__file__).resolve().parents[1]
_EDU_CONTROLLERS = REPO_ROOT / "domain-packs" / "education" / "controllers"
if str(_EDU_CONTROLLERS) not in sys.path:
    sys.path.insert(0, str(_EDU_CONTROLLERS))


def _load_governance_adapters():
    spec = importlib.util.spec_from_file_location(
        "edu_governance_adapters_test",
        str(_EDU_CONTROLLERS / "governance_adapters.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── can_govern_domain with registry ──────────────────────────────────────────


def _mock_registry(domain_id: str = "education", module_ids: list[str] | None = None):
    """Build a minimal mock registry for can_govern_domain tests."""
    reg = MagicMock()
    reg.resolve_domain_id.return_value = domain_id
    reg.list_modules_for_domain.return_value = [
        {"module_id": mid} for mid in (module_ids or ["domain/edu/algebra-level-1/v1"])
    ]
    return reg


@pytest.mark.unit
def test_can_govern_domain_direct_match_still_works() -> None:
    """Backward compat: direct domain names in governed_modules still match."""
    user = {"role": "admin", "governed_modules": ["education"]}
    assert can_govern_domain(user, "education") is True
    assert can_govern_domain(user, "agriculture") is False


@pytest.mark.unit
def test_can_govern_domain_root_bypass() -> None:
    assert can_govern_domain({"role": "root"}, "anything") is True


@pytest.mark.unit
def test_can_govern_domain_non_da_rejected() -> None:
    assert can_govern_domain({"role": "user"}, "education") is False


@pytest.mark.unit
def test_can_govern_domain_module_id_with_registry() -> None:
    """When governed_modules has module IDs, registry resolves the domain."""
    user = {
        "role": "admin",
        "governed_modules": ["domain/edu/algebra-level-1/v1"],
    }
    reg = _mock_registry("education", ["domain/edu/algebra-level-1/v1"])
    assert can_govern_domain(user, "education", registry=reg) is True
    reg.resolve_domain_id.assert_called_with("education")


@pytest.mark.unit
def test_can_govern_domain_module_id_wrong_domain() -> None:
    """DA governing education modules cannot access agriculture."""
    user = {
        "role": "admin",
        "governed_modules": ["domain/edu/algebra-level-1/v1"],
    }
    reg = MagicMock()
    reg.resolve_domain_id.return_value = "agriculture"
    reg.list_modules_for_domain.return_value = [
        {"module_id": "domain/agri/operations-level-1/v1"},
    ]
    assert can_govern_domain(user, "agriculture", registry=reg) is False


@pytest.mark.unit
def test_can_govern_domain_without_registry_module_id_fails() -> None:
    """Without registry, module IDs don't match domain names."""
    user = {
        "role": "admin",
        "governed_modules": ["domain/edu/algebra-level-1/v1"],
    }
    # No registry — "education" not literally in governed_modules
    assert can_govern_domain(user, "education") is False


@pytest.mark.unit
def test_can_govern_domain_via_domain_roles_direct() -> None:
    """DA with domain_roles key matching domain_id passes without registry."""
    user = {
        "role": "admin",
        "governed_modules": [],
        "domain_roles": {"education": "admin"},
    }
    assert can_govern_domain(user, "education") is True
    assert can_govern_domain(user, "agriculture") is False


@pytest.mark.unit
def test_can_govern_domain_via_domain_roles_with_registry() -> None:
    """DA with module-level domain_roles keys passes via registry lookup."""
    user = {
        "role": "admin",
        "governed_modules": [],
        "domain_roles": {"domain/edu/algebra-level-1/v1": "teacher"},
    }
    reg = _mock_registry("education", ["domain/edu/algebra-level-1/v1"])
    assert can_govern_domain(user, "education", registry=reg) is True


@pytest.mark.unit
def test_can_govern_domain_empty_governed_and_roles() -> None:
    """DA with neither governed_modules nor domain_roles has unrestricted access.

    This matches the invite_user design where governed_modules=None means
    "all modules".  The None is stored as [] in persistence/JWT, so a DA
    promoted without explicit scope should still be able to govern any domain.
    """
    user = {
        "role": "admin",
        "governed_modules": [],
        "domain_roles": {},
    }
    reg = _mock_registry("education", ["domain/edu/algebra-level-1/v1"])
    assert can_govern_domain(user, "education", registry=reg) is True


@pytest.mark.unit
def test_can_govern_domain_unrestricted_da_no_registry() -> None:
    """Unrestricted DA (empty governed + empty domain_roles) passes even without registry."""
    user = {"role": "admin", "governed_modules": [], "domain_roles": {}}
    assert can_govern_domain(user, "anything") is True


@pytest.mark.unit
def test_can_govern_domain_unrestricted_da_missing_keys() -> None:
    """DA with no governed_modules/domain_roles keys at all passes (unrestricted)."""
    user = {"role": "admin"}
    assert can_govern_domain(user, "education") is True


@pytest.mark.unit
def test_can_govern_domain_scoped_da_wrong_domain() -> None:
    """DA with specific governed_modules cannot access other domains."""
    user = {
        "role": "admin",
        "governed_modules": ["agriculture"],
        "domain_roles": {},
    }
    assert can_govern_domain(user, "education") is False


# ── list_users domain filtering ──────────────────────────────────────────────


def _setup_admin_config(monkeypatch, users, registry=None):
    """Patch _cfg for _execute_admin_operation tests."""
    from lumina.api import config as _cfg

    mock_persistence = MagicMock()
    mock_persistence.list_users.return_value = users
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    original_persistence = _cfg.PERSISTENCE
    original_registry = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    if registry is not None:
        _cfg.DOMAIN_REGISTRY = registry
    return original_persistence, original_registry


def _teardown_admin_config(original_persistence, original_registry):
    from lumina.api import config as _cfg
    _cfg.PERSISTENCE = original_persistence
    _cfg.DOMAIN_REGISTRY = original_registry


def _edu_registry():
    """Mock registry that knows education domain has algebra module."""
    _domain_map = {
        "education": "education",
        "edu": "education",
        "agriculture": "agriculture",
        "agri": "agriculture",
    }

    def _resolve(d):
        if d in _domain_map:
            return _domain_map[d]
        from lumina.core.domain_registry import DomainNotFoundError
        raise DomainNotFoundError(d)

    reg = MagicMock()
    reg.resolve_domain_id.side_effect = _resolve
    reg.list_modules_for_domain.side_effect = lambda d: {
        "education": [
            {"module_id": "domain/edu/algebra-level-1/v1"},
            {"module_id": "domain/edu/pre-algebra/v1"},
        ],
        "agriculture": [
            {"module_id": "domain/agri/operations-level-1/v1"},
        ],
    }.get(d, [])
    reg.list_domains.return_value = [
        {"domain_id": "education", "runtime_config_path": "domain-packs/education/cfg/runtime-config.yaml"},
        {"domain_id": "agriculture", "runtime_config_path": "domain-packs/agriculture/cfg/runtime-config.yaml"},
    ]
    return reg


@pytest.mark.unit
def test_list_users_domain_id_filter(monkeypatch) -> None:
    """list_users with domain_id returns only users in that domain's modules."""
    from lumina.api.routes.admin import _execute_admin_operation

    users = [
        {"user_id": "u1", "username": "alice", "role": "user",
         "governed_modules": ["domain/edu/algebra-level-1/v1"]},
        {"user_id": "u2", "username": "bob", "role": "user",
         "governed_modules": ["domain/agri/operations-level-1/v1"]},
        {"user_id": "u3", "username": "carol", "role": "user",
         "domain_roles": {"domain/edu/algebra-level-1/v1": "student"}},
    ]
    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, users, registry=reg)
    try:
        result = asyncio.run(_execute_admin_operation(
            {"sub": "root", "role": "root"},
            {"operation": "list_users", "target": "", "params": {"domain_id": "education"}},
            "list users in education",
        ))
    finally:
        _teardown_admin_config(orig_p, orig_r)

    assert result["count"] == 2
    user_ids = {u["user_id"] for u in result["users"]}
    assert user_ids == {"u1", "u3"}


@pytest.mark.unit
def test_list_users_module_id_filter(monkeypatch) -> None:
    """list_users with module_id returns only users in that specific module."""
    from lumina.api.routes.admin import _execute_admin_operation

    users = [
        {"user_id": "u1", "username": "alice", "role": "user",
         "governed_modules": ["domain/edu/algebra-level-1/v1"]},
        {"user_id": "u2", "username": "bob", "role": "user",
         "governed_modules": ["domain/edu/pre-algebra/v1"]},
    ]
    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, users, registry=reg)
    try:
        result = asyncio.run(_execute_admin_operation(
            {"sub": "root", "role": "root"},
            {"operation": "list_users", "target": "",
             "params": {"module_id": "domain/edu/algebra-level-1/v1"}},
            "list users in algebra module",
        ))
    finally:
        _teardown_admin_config(orig_p, orig_r)

    assert result["count"] == 1
    assert result["users"][0]["user_id"] == "u1"


@pytest.mark.unit
def test_list_users_domain_role_filter(monkeypatch) -> None:
    """list_users with domain_role filter returns only matching users."""
    from lumina.api.routes.admin import _execute_admin_operation

    users = [
        {"user_id": "u1", "username": "alice", "role": "user",
         "domain_roles": {"domain/edu/algebra-level-1/v1": "student"}},
        {"user_id": "u2", "username": "bob", "role": "user",
         "domain_roles": {"domain/edu/algebra-level-1/v1": "teacher"}},
        {"user_id": "u3", "username": "carol", "role": "user",
         "domain_roles": {}},
    ]
    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, users, registry=reg)
    try:
        result = asyncio.run(_execute_admin_operation(
            {"sub": "root", "role": "root"},
            {"operation": "list_users", "target": "",
             "params": {"domain_role": "student"}},
            "list students",
        ))
    finally:
        _teardown_admin_config(orig_p, orig_r)

    assert result["count"] == 1
    assert result["users"][0]["user_id"] == "u1"


@pytest.mark.unit
def test_da_list_users_cross_domain_rejected(monkeypatch) -> None:
    """DA governing education cannot list users in agriculture."""
    from lumina.api.routes.admin import _execute_admin_operation
    from fastapi import HTTPException

    users = [
        {"user_id": "u1", "username": "alice", "role": "user",
         "governed_modules": ["domain/agri/operations-level-1/v1"]},
    ]
    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, users, registry=reg)
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_execute_admin_operation(
                {"sub": "da-edu", "role": "admin",
                 "governed_modules": ["domain/edu/algebra-level-1/v1"]},
                {"operation": "list_users", "target": "",
                 "params": {"domain_id": "agriculture"}},
                "list users in agriculture",
            ))
        assert exc_info.value.status_code == 403
    finally:
        _teardown_admin_config(orig_p, orig_r)


@pytest.mark.unit
def test_da_list_users_own_domain_allowed(monkeypatch) -> None:
    """DA governing education can list users in education."""
    from lumina.api.routes.admin import _execute_admin_operation

    users = [
        {"user_id": "u1", "username": "alice", "role": "user",
         "governed_modules": ["domain/edu/algebra-level-1/v1"]},
        {"user_id": "u2", "username": "bob", "role": "user",
         "governed_modules": ["domain/agri/operations-level-1/v1"]},
    ]
    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, users, registry=reg)
    try:
        result = asyncio.run(_execute_admin_operation(
            {"sub": "da-edu", "role": "admin",
             "governed_modules": ["domain/edu/algebra-level-1/v1"]},
            {"operation": "list_users", "target": "",
             "params": {"domain_id": "education"}},
            "list users in education",
        ))
    finally:
        _teardown_admin_config(orig_p, orig_r)

    # DA scoping: should only see users in their governed modules
    assert result["count"] == 1
    assert result["users"][0]["user_id"] == "u1"


@pytest.mark.unit
def test_da_list_users_module_cross_domain_rejected(monkeypatch) -> None:
    """DA governing education cannot filter by agriculture module."""
    from lumina.api.routes.admin import _execute_admin_operation
    from fastapi import HTTPException

    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, [], registry=reg)
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_execute_admin_operation(
                {"sub": "da-edu", "role": "admin",
                 "governed_modules": ["domain/edu/algebra-level-1/v1"]},
                {"operation": "list_users", "target": "",
                 "params": {"module_id": "domain/agri/operations-level-1/v1"}},
                "list users in agri module",
            ))
        assert exc_info.value.status_code == 403
    finally:
        _teardown_admin_config(orig_p, orig_r)


# ── list_escalations domain boundary ────────────────────────────────────────


@pytest.mark.unit
def test_da_list_escalations_cross_domain_rejected(monkeypatch) -> None:
    """DA governing education cannot query agriculture escalations."""
    from lumina.api.routes.admin import _execute_admin_operation
    from fastapi import HTTPException

    reg = _edu_registry()
    orig_p, orig_r = _setup_admin_config(monkeypatch, [], registry=reg)
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_execute_admin_operation(
                {"sub": "da-edu", "role": "admin",
                 "governed_modules": ["domain/edu/algebra-level-1/v1"]},
                {"operation": "list_escalations", "target": "",
                 "params": {"domain_id": "agriculture"}},
                "list escalations in agriculture",
            ))
        assert exc_info.value.status_code == 403
    finally:
        _teardown_admin_config(orig_p, orig_r)


# ── _normalize_slm_command domain inference ──────────────────────────────────


@pytest.mark.unit
def test_normalize_infers_domain_for_list_users(monkeypatch) -> None:
    """_normalize_slm_command infers domain_id for list_users from instruction."""
    from lumina.api.routes.admin import _normalize_slm_command
    from lumina.api import config as _cfg

    reg = _edu_registry()
    original = _cfg.DOMAIN_REGISTRY
    _cfg.DOMAIN_REGISTRY = reg
    try:
        cmd = {
            "operation": "list_users",
            "target": "",
            "params": {},
        }
        result = _normalize_slm_command(cmd, "list users in education domain")
        assert result["params"]["domain_id"] == "education"
    finally:
        _cfg.DOMAIN_REGISTRY = original


@pytest.mark.unit
def test_normalize_infers_domain_for_list_escalations(monkeypatch) -> None:
    """_normalize_slm_command infers domain_id for list_escalations."""
    from lumina.api.routes.admin import _normalize_slm_command
    from lumina.api import config as _cfg

    reg = _edu_registry()
    original = _cfg.DOMAIN_REGISTRY
    _cfg.DOMAIN_REGISTRY = reg
    try:
        cmd = {
            "operation": "list_escalations",
            "target": "",
            "params": {},
        }
        result = _normalize_slm_command(cmd, "show escalations for education")
        assert result["params"]["domain_id"] == "education"
    finally:
        _cfg.DOMAIN_REGISTRY = original


@pytest.mark.unit
def test_normalize_infers_domain_for_list_modules(monkeypatch) -> None:
    """_normalize_slm_command infers domain_id for list_modules."""
    from lumina.api.routes.admin import _normalize_slm_command
    from lumina.api import config as _cfg

    reg = _edu_registry()
    original = _cfg.DOMAIN_REGISTRY
    _cfg.DOMAIN_REGISTRY = reg
    try:
        cmd = {
            "operation": "list_modules",
            "target": "",
            "params": {},
        }
        result = _normalize_slm_command(cmd, "list modules in education")
        assert result["params"]["domain_id"] == "education"
    finally:
        _cfg.DOMAIN_REGISTRY = original


@pytest.mark.unit
def test_normalize_does_not_override_existing_domain_id() -> None:
    """If domain_id is already set, _normalize_slm_command keeps it."""
    from lumina.api.routes.admin import _normalize_slm_command
    from lumina.api import config as _cfg

    reg = _edu_registry()
    original = _cfg.DOMAIN_REGISTRY
    _cfg.DOMAIN_REGISTRY = reg
    try:
        cmd = {
            "operation": "list_users",
            "target": "",
            "params": {"domain_id": "agriculture"},
        }
        result = _normalize_slm_command(cmd, "list users in education domain")
        assert result["params"]["domain_id"] == "agriculture"
    finally:
        _cfg.DOMAIN_REGISTRY = original


# ── Education NLP domain injection ───────────────────────────────────────────


@pytest.mark.unit
def test_education_fallback_injects_domain_for_list_users() -> None:
    """Education _deterministic_command_fallback injects domain_id: education."""
    mod = _load_governance_adapters()
    result = mod._deterministic_command_fallback("list users", {"query_type": "admin_command"})
    assert result is not None
    assert result["operation"] == "list_users"
    assert result["params"]["domain_id"] == "education"


@pytest.mark.unit
def test_education_fallback_injects_domain_for_list_escalations() -> None:
    mod = _load_governance_adapters()
    result = mod._deterministic_command_fallback("list escalations", {"query_type": "admin_command"})
    assert result is not None
    assert result["operation"] == "list_escalations"
    assert result["params"]["domain_id"] == "education"


@pytest.mark.unit
def test_education_fallback_injects_domain_for_list_modules() -> None:
    mod = _load_governance_adapters()
    result = mod._deterministic_command_fallback("show modules", {"query_type": "admin_command"})
    assert result is not None
    assert result["operation"] == "list_modules"
    assert result["params"]["domain_id"] == "education"
