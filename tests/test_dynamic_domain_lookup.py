"""Tests for dynamic domain lookup, prefix resolution, and discovery operations.

Covers:
- resolve_domain_id prefix / path-style resolution
- list_domain_rbac_roles admin operation
- get_domain_module_manifest admin operation
- list_users admin operation
- get_domain_physics admin operation
- list_daemon_tasks admin operation
- Absence of hardcoded domain knowledge in command-interpreter-spec-v1.md
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lumina.core.domain_registry import DomainNotFoundError, DomainRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def registry() -> DomainRegistry:
    """Multi-domain registry from real domain-registry.yaml."""
    return DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path="domain-packs/system/cfg/domain-registry.yaml",
    )


# ── resolve_domain_id — exact match ────────────────────────────


@pytest.mark.unit
def test_resolve_exact_education(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("education") == "education"


@pytest.mark.unit
def test_resolve_exact_agriculture(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("agriculture") == "agriculture"


@pytest.mark.unit
def test_resolve_exact_system(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("system") == "system"


# ── resolve_domain_id — prefix shorthand ───────────────────────


@pytest.mark.unit
def test_resolve_prefix_edu(registry: DomainRegistry) -> None:
    """'edu' prefix maps to 'education' via module_prefix."""
    assert registry.resolve_domain_id("edu") == "education"


@pytest.mark.unit
def test_resolve_prefix_agri(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("agri") == "agriculture"


@pytest.mark.unit
def test_resolve_prefix_sys(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("sys") == "system"


# ── resolve_domain_id — path-style inputs ──────────────────────


@pytest.mark.unit
def test_resolve_path_domain_edu(registry: DomainRegistry) -> None:
    """'domain/edu' strips prefix and resolves via module_prefix."""
    assert registry.resolve_domain_id("domain/edu") == "education"


@pytest.mark.unit
def test_resolve_path_domain_edu_with_module(registry: DomainRegistry) -> None:
    """'domain/edu/algebra-level-1/v1' extracts 'edu' and resolves."""
    assert registry.resolve_domain_id("domain/edu/algebra-level-1/v1") == "education"


@pytest.mark.unit
def test_resolve_path_domain_agri_with_module(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("domain/agri/operations-level-1/v1") == "agriculture"


@pytest.mark.unit
def test_resolve_path_domain_sys(registry: DomainRegistry) -> None:
    assert registry.resolve_domain_id("domain/sys") == "system"


# ── resolve_domain_id — error cases ───────────────────────────


@pytest.mark.unit
def test_resolve_unknown_raises(registry: DomainRegistry) -> None:
    with pytest.raises(DomainNotFoundError):
        registry.resolve_domain_id("nonexistent")


@pytest.mark.unit
def test_resolve_unknown_path_raises(registry: DomainRegistry) -> None:
    with pytest.raises(DomainNotFoundError):
        registry.resolve_domain_id("domain/zzz/module/v1")


@pytest.mark.unit
def test_resolve_none_returns_default(registry: DomainRegistry) -> None:
    """None domain_id falls back to default_domain (education)."""
    assert registry.resolve_domain_id(None) == "education"


@pytest.mark.unit
def test_resolve_empty_string_returns_default(registry: DomainRegistry) -> None:
    """Empty string is falsy → falls back to default_domain."""
    assert registry.resolve_domain_id("") == "education"


# ── list_modules_for_domain — basic ────────────────────────────


@pytest.mark.unit
def test_list_modules_education(registry: DomainRegistry) -> None:
    """Education domain returns at least one module with an id and physics path."""
    modules = registry.list_modules_for_domain("education")
    assert len(modules) >= 1
    for mod in modules:
        assert "module_id" in mod
        assert "domain_physics_path" in mod


@pytest.mark.unit
def test_list_modules_system(registry: DomainRegistry) -> None:
    modules = registry.list_modules_for_domain("system")
    assert len(modules) >= 1


@pytest.mark.unit
def test_list_modules_unknown_raises(registry: DomainRegistry) -> None:
    with pytest.raises(DomainNotFoundError):
        registry.list_modules_for_domain("nonexistent")


# ── Domain-role-aliases accessible from physics files ──────────


@pytest.mark.unit
def test_system_domain_has_role_aliases() -> None:
    """system-core domain-physics.json contains domain_role_aliases under governance."""
    dp_path = _REPO_ROOT / "domain-packs/system/modules/system-core/domain-physics.json"
    dp = json.loads(dp_path.read_text(encoding="utf-8"))
    aliases = dp["subsystem_configs"]["governance"]["domain_role_aliases"]
    assert isinstance(aliases, dict)
    assert len(aliases) > 0
    # Known aliases: student → user, teacher → user
    assert aliases.get("student") == "user"
    assert aliases.get("teacher") == "user"


# ── Command interpreter spec: no hardcoded domain knowledge ───


_FORBIDDEN_PATTERNS = [
    "algebra-level-1",
    "pre-algebra",
    "algebra-intro",
    "operations-level-1",
]


@pytest.mark.unit
def test_command_interpreter_spec_has_no_hardcoded_modules() -> None:
    """The command interpreter spec must not contain hardcoded module IDs."""
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8").lower()
    for pattern in _FORBIDDEN_PATTERNS:
        assert pattern not in content, (
            f"Hardcoded module ID '{pattern}' found in command-interpreter-spec"
        )


@pytest.mark.unit
def test_command_interpreter_spec_has_no_hardcoded_domain_roles() -> None:
    """The spec must not enumerate domain-specific roles as known values."""
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8").lower()
    # These were previously hardcoded in the role-mapping table
    for role in ["field_operator", "site_manager", "teaching_assistant"]:
        assert role not in content, (
            f"Hardcoded domain role '{role}' found in command-interpreter-spec"
        )


@pytest.mark.unit
def test_command_interpreter_spec_mentions_dynamic_discovery() -> None:
    """The spec should reference dynamic discovery operations."""
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8").lower()
    assert "list_domain_rbac_roles" in content
    assert "get_domain_module_manifest" in content


# ── No remaining night_cycle references in governance files ───


_GOVERNANCE_FILES = [
    "domain-packs/system/modules/system-core/domain-physics.json",
    "domain-packs/system/prompts/domain-persona-v1.md",
    "domain-packs/system/cfg/runtime-config.yaml",
    "domain-packs/system/cfg/admin-operations.yaml",
]


@pytest.mark.unit
@pytest.mark.parametrize("rel_path", _GOVERNANCE_FILES)
def test_no_trigger_night_cycle_in_governance(rel_path: str) -> None:
    fpath = _REPO_ROOT / rel_path
    if not fpath.exists():
        pytest.skip(f"{rel_path} not found")
    content = fpath.read_text(encoding="utf-8")
    assert "trigger_night_cycle" not in content, f"trigger_night_cycle in {rel_path}"
    assert "night_cycle_status" not in content, f"night_cycle_status in {rel_path}"


@pytest.mark.unit
def test_admin_operations_has_daemon_ops() -> None:
    fpath = _REPO_ROOT / "domain-packs" / "system" / "cfg" / "admin-operations.yaml"
    content = fpath.read_text(encoding="utf-8")
    assert "trigger_daemon_task" in content
    assert "daemon_status" in content
    assert "list_domain_rbac_roles" in content
    assert "get_domain_module_manifest" in content


@pytest.mark.unit
def test_admin_operations_has_new_discovery_ops() -> None:
    """admin-operations.yaml includes list_users, get_domain_physics, list_daemon_tasks."""
    fpath = _REPO_ROOT / "domain-packs" / "system" / "cfg" / "admin-operations.yaml"
    content = fpath.read_text(encoding="utf-8")
    assert "list_users" in content
    assert "get_domain_physics" in content
    assert "list_daemon_tasks" in content


# ── Domain-physics.json includes all discovery operations ──────


@pytest.mark.unit
def test_domain_physics_operation_ids_complete() -> None:
    """All discovery operations are in the domain-physics operation_ids list."""
    dp_path = _REPO_ROOT / "domain-packs/system/modules/system-core/domain-physics.json"
    dp = json.loads(dp_path.read_text(encoding="utf-8"))
    op_ids = dp["subsystem_configs"]["admin_operations"]["operation_ids"]
    for op in [
        "list_users", "get_domain_physics", "list_daemon_tasks",
        "list_domain_rbac_roles", "get_domain_module_manifest",
        "list_domains", "list_modules", "list_commands",
    ]:
        assert op in op_ids, f"{op} missing from operation_ids"


@pytest.mark.unit
def test_domain_physics_hitl_exempt_complete() -> None:
    """All discovery operations are in the hitl_policy.system_exempt list."""
    dp_path = _REPO_ROOT / "domain-packs/system/modules/system-core/domain-physics.json"
    dp = json.loads(dp_path.read_text(encoding="utf-8"))
    exempt = dp["subsystem_configs"]["admin_operations"]["hitl_policy"]["system_exempt"]
    for op in [
        "list_users", "get_domain_physics", "list_daemon_tasks",
        "list_domain_rbac_roles", "get_domain_module_manifest",
    ]:
        assert op in exempt, f"{op} missing from hitl_policy.system_exempt"


@pytest.mark.unit
def test_domain_physics_min_role_for_sensitive_ops() -> None:
    """list_users requires it_support; get_domain_physics requires domain_authority."""
    dp_path = _REPO_ROOT / "domain-packs/system/modules/system-core/domain-physics.json"
    dp = json.loads(dp_path.read_text(encoding="utf-8"))
    min_role = dp["subsystem_configs"]["governance"]["min_role_policy"]
    assert min_role["list_users"] == "it_support"
    assert min_role["get_domain_physics"] == "domain_authority"
    assert min_role["list_daemon_tasks"] == "domain_authority"


# ── Command interpreter spec references new discovery ops ──────


@pytest.mark.unit
def test_command_interpreter_spec_mentions_list_users() -> None:
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "list_users" in content


@pytest.mark.unit
def test_command_interpreter_spec_mentions_get_domain_physics() -> None:
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "get_domain_physics" in content


@pytest.mark.unit
def test_command_interpreter_spec_mentions_list_daemon_tasks() -> None:
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "list_daemon_tasks" in content


# ── Admin operation handler unit tests ─────────────────────────


@pytest.mark.unit
def test_list_users_handler_returns_users() -> None:
    """list_users operation returns user records without password_hash."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.list_users.return_value = [
        {"user_id": "u1", "username": "alice", "role": "root", "active": True},
        {"user_id": "u2", "username": "bob", "role": "user", "active": True, "password_hash": "SHOULD_NOT_APPEAR"},
    ]
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "list_users",
        "target": "",
        "params": {},
    }

    original_persistence = _cfg.PERSISTENCE
    _cfg.PERSISTENCE = mock_persistence
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "list users"))
    finally:
        _cfg.PERSISTENCE = original_persistence

    assert result["operation"] == "list_users"
    assert result["count"] == 2
    for u in result["users"]:
        assert "password_hash" not in u


@pytest.mark.unit
def test_list_users_handler_filters_by_role() -> None:
    """list_users with role filter returns only matching users."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.list_users.return_value = [
        {"user_id": "u1", "username": "alice", "role": "root", "active": True},
        {"user_id": "u2", "username": "bob", "role": "user", "active": True},
        {"user_id": "u3", "username": "carol", "role": "user", "active": True},
    ]
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "list_users",
        "target": "",
        "params": {"role": "user"},
    }

    original_persistence = _cfg.PERSISTENCE
    _cfg.PERSISTENCE = mock_persistence
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "list users with role user"))
    finally:
        _cfg.PERSISTENCE = original_persistence

    assert result["count"] == 2
    assert all(u["role"] == "user" for u in result["users"])


@pytest.mark.unit
def test_get_domain_physics_handler_returns_physics(registry: DomainRegistry) -> None:
    """get_domain_physics returns governance fields for a domain."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "get_domain_physics",
        "target": "system",
        "params": {"domain_id": "system"},
    }

    original_persistence = _cfg.PERSISTENCE
    original_registry = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    _cfg.DOMAIN_REGISTRY = registry
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "show physics for system"))
    finally:
        _cfg.PERSISTENCE = original_persistence
        _cfg.DOMAIN_REGISTRY = original_registry

    assert result["operation"] == "get_domain_physics"
    assert result["domain_id"] == "system"
    assert result["count"] >= 1
    # Should include governance info
    entry = result["physics"][0]
    assert "module_id" in entry
    assert "governance" in entry or "label" in entry


@pytest.mark.unit
def test_list_daemon_tasks_handler_returns_tasks() -> None:
    """list_daemon_tasks returns the task priority list."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "list_daemon_tasks",
        "target": "",
        "params": {},
    }

    original_persistence = _cfg.PERSISTENCE
    _cfg.PERSISTENCE = mock_persistence
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "list daemon tasks"))
    finally:
        _cfg.PERSISTENCE = original_persistence

    assert result["operation"] == "list_daemon_tasks"
    # Should have tasks from runtime config
    assert isinstance(result["tasks"], list)
    assert result["count"] == len(result["tasks"])
    assert "daemon_state" in result
    assert "daemon_enabled" in result


# ── Schema files exist for all new operations ──────────────────


@pytest.mark.unit
@pytest.mark.parametrize("schema_name", [
    "list-users", "get-domain-physics", "list-daemon-tasks",
    "list-domain-rbac-roles", "get-domain-module-manifest",
    "daemon-status", "trigger-daemon-task",
])
def test_admin_command_schema_exists(schema_name: str) -> None:
    """Each discovery operation has a JSON schema in standards/admin-command-schemas/."""
    schema_path = _REPO_ROOT / "standards" / "admin-command-schemas" / f"{schema_name}.json"
    assert schema_path.exists(), f"Schema missing: {schema_name}.json"
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "description" in data
    assert "schema_version" in data


# ── resource-monitor-daemon.md has no night-cycle references ───


@pytest.mark.unit
def test_resource_monitor_daemon_doc_no_night_cycle() -> None:
    """resource-monitor-daemon.md should not reference night cycle."""
    doc_path = _REPO_ROOT / "docs" / "7-concepts" / "resource-monitor-daemon.md"
    if not doc_path.exists():
        pytest.skip("Doc not found")
    content = doc_path.read_text(encoding="utf-8")
    assert "night_cycle" not in content.lower().replace("-", "_").replace(" ", "_"), \
        "Night cycle reference found in resource-monitor-daemon.md"
    assert "NightCycleScheduler" not in content, \
        "NightCycleScheduler reference found in resource-monitor-daemon.md"
    assert "night-cycle-processing.md" not in content, \
        "Link to night-cycle-processing.md found in resource-monitor-daemon.md"
