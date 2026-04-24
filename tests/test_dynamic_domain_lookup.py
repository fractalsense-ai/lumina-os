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
    from lumina.core.runtime_loader import load_runtime_context
    return DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path="domain-packs/system/cfg/domain-registry.yaml",
        load_runtime_context_fn=load_runtime_context,
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
def test_system_domain_has_no_static_role_aliases() -> None:
    """system-core domain-physics.json no longer contains static domain_role_aliases.

    Phase 7D replaced flat aliases with dynamic aggregation from domain
    physics files.  The static block should NOT be present.
    """
    dp_path = _REPO_ROOT / "domain-packs/system/modules/system-core/domain-physics.json"
    dp = json.loads(dp_path.read_text(encoding="utf-8"))
    gov = dp.get("subsystem_configs", {}).get("governance", {})
    assert "domain_role_aliases" not in gov, (
        "Static domain_role_aliases should have been removed in Phase 7D"
    )


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


# ── No remaining nightcycle references in governance files ───


_GOVERNANCE_FILES = [
    "domain-packs/system/modules/system-core/domain-physics.json",
    "domain-packs/system/prompts/domain-persona-v1.md",
    "domain-packs/system/cfg/runtime-config.yaml",
    "domain-packs/system/cfg/admin-operations.yaml",
]


@pytest.mark.unit
@pytest.mark.parametrize("rel_path", _GOVERNANCE_FILES)
def test_no_nightcycle_ops_in_governance(rel_path: str) -> None:
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
    """list_users and invite_user require admin; get_domain_physics requires admin."""
    dp_path = _REPO_ROOT / "domain-packs/system/modules/system-core/domain-physics.json"
    dp = json.loads(dp_path.read_text(encoding="utf-8"))
    min_role = dp["subsystem_configs"]["governance"]["min_role_policy"]
    assert min_role["list_users"] == "admin"
    assert min_role["invite_user"] == "admin"
    assert min_role["get_domain_physics"] == "admin"
    assert min_role["list_daemon_tasks"] == "admin"


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


# ── resource-monitor-daemon.md has no nightcycle references ───


@pytest.mark.unit
def test_resource_monitor_daemon_doc_no_nightcycle() -> None:
    """resource-monitor-daemon.md should not reference nightcycle."""
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


# ── Phase 6: Default modules, governed_modules, request_module_assignment ──


@pytest.mark.unit
def test_default_module_exists_education() -> None:
    """Education domain has a general-education default module (Student Commons)."""
    dp = _REPO_ROOT / "domain-packs/education/modules/general-education/domain-physics.json"
    assert dp.exists()
    data = json.loads(dp.read_text(encoding="utf-8"))
    assert data["id"] == "domain/edu/general-education/v1"
    # Student Commons has a hard-safety invariant and a privacy invariant
    assert len(data["invariants"]) == 2
    assert data["invariants"][0]["id"] == "content_safety_hard"
    # And safety + journaling standing orders
    assert len(data["standing_orders"]) == 4


@pytest.mark.unit
def test_default_module_exists_agriculture() -> None:
    """Agriculture domain has a general-operations default module."""
    dp = _REPO_ROOT / "domain-packs/agriculture/modules/general-operations/domain-physics.json"
    assert dp.exists()
    data = json.loads(dp.read_text(encoding="utf-8"))
    assert data["id"] == "domain/agri/general-operations/v1"
    assert data["invariants"] == []


@pytest.mark.unit
def test_pack_yaml_has_default_module_education() -> None:
    """Education pack.yaml declares default_module."""
    from lumina.core.yaml_loader import load_yaml
    pack = load_yaml(str(_REPO_ROOT / "domain-packs/education/pack.yaml"))
    assert pack.get("default_module") == "general-education"
    assert "general-education" in (pack.get("modules") or [])


@pytest.mark.unit
def test_pack_yaml_has_default_module_agriculture() -> None:
    """Agriculture pack.yaml declares default_module."""
    from lumina.core.yaml_loader import load_yaml
    pack = load_yaml(str(_REPO_ROOT / "domain-packs/agriculture/pack.yaml"))
    assert pack.get("default_module") == "general-operations"
    assert "general-operations" in (pack.get("modules") or [])


@pytest.mark.unit
def test_get_default_module_id_education(registry: DomainRegistry) -> None:
    """Registry can resolve default module ID for education domain."""
    mod_id = registry.get_default_module_id("education")
    assert mod_id is not None
    assert "general-education" in mod_id


@pytest.mark.unit
def test_get_default_module_id_agriculture(registry: DomainRegistry) -> None:
    """Registry can resolve default module ID for agriculture domain."""
    mod_id = registry.get_default_module_id("agriculture")
    assert mod_id is not None
    assert "general-operations" in mod_id


@pytest.mark.unit
def test_get_default_module_id_none_for_system(registry: DomainRegistry) -> None:
    """System domain has no default module (returns None)."""
    mod_id = registry.get_default_module_id("system")
    assert mod_id is None


@pytest.mark.unit
def test_governed_modules_stripped_for_non_da() -> None:
    """_normalize_slm_command strips governed_modules for non-DA roles."""
    from lumina.api.routes.admin import _normalize_slm_command
    cmd = {
        "operation": "invite_user",
        "target": "TestUser",
        "params": {
            "username": "TestUser",
            "role": "user",
            "governed_modules": ["domain/edu/algebra-level-1/v1"],
        },
    }
    result = _normalize_slm_command(cmd)
    assert "governed_modules" not in result.get("params", {})


@pytest.mark.unit
def test_governed_modules_kept_for_da() -> None:
    """_normalize_slm_command preserves governed_modules for admin."""
    from lumina.api.routes.admin import _normalize_slm_command
    cmd = {
        "operation": "invite_user",
        "target": "DAUser",
        "params": {
            "username": "DAUser",
            "role": "admin",
            "governed_modules": ["domain/edu/algebra-level-1/v1"],
        },
    }
    result = _normalize_slm_command(cmd)
    assert result["params"].get("governed_modules") == ["domain/edu/algebra-level-1/v1"]


@pytest.mark.unit
def test_governed_modules_null_accepted_for_da() -> None:
    """invite_user handler accepts governed_modules=None for admin."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.get_user_by_username.return_value = None
    mock_persistence.create_user = MagicMock()
    mock_persistence.set_user_invite_token = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root", "username": "admin"}
    parsed = {
        "operation": "invite_user",
        "target": "NewDA",
        "params": {
            "username": "NewDA",
            "role": "admin",
        },
    }

    original = _cfg.PERSISTENCE
    _cfg.PERSISTENCE = mock_persistence
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "create DA"))
    finally:
        _cfg.PERSISTENCE = original

    assert result["operation"] == "invite_user"
    assert result["username"] == "NewDA"
    # Should not raise — governed_modules=None is valid for DA


@pytest.mark.unit
def test_request_module_assignment_handler(registry: DomainRegistry) -> None:
    """request_module_assignment creates an escalation record."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "user1", "role": "user", "username": "student1"}
    parsed = {
        "operation": "request_module_assignment",
        "target": "education",
        "params": {
            "domain_id": "education",
            "module_id": "domain/edu/algebra-level-1/v1",
            "reason": "Want to start algebra",
        },
    }

    original_p = _cfg.PERSISTENCE
    original_r = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    _cfg.DOMAIN_REGISTRY = registry
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "request module"))
    finally:
        _cfg.PERSISTENCE = original_p
        _cfg.DOMAIN_REGISTRY = original_r

    assert result["operation"] == "request_module_assignment"
    assert result["status"] == "pending_approval"
    assert result["domain_id"] == "education"
    assert result["module_id"] == "domain/edu/algebra-level-1/v1"
    assert "escalation_id" in result
    # Escalation record + TraceEvent = 2 log writes
    assert mock_persistence.append_log_record.call_count == 2


@pytest.mark.unit
def test_request_module_assignment_invalid_module(registry: DomainRegistry) -> None:
    """request_module_assignment rejects invalid module IDs."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    from fastapi import HTTPException
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "user1", "role": "user"}
    parsed = {
        "operation": "request_module_assignment",
        "target": "education",
        "params": {
            "domain_id": "education",
            "module_id": "domain/edu/nonexistent/v1",
        },
    }

    original_p = _cfg.PERSISTENCE
    original_r = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    _cfg.DOMAIN_REGISTRY = registry
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_execute_admin_operation(user_data, parsed, "request module"))
        assert exc_info.value.status_code == 422
    finally:
        _cfg.PERSISTENCE = original_p
        _cfg.DOMAIN_REGISTRY = original_r


@pytest.mark.unit
def test_command_interpreter_spec_has_request_module_assignment() -> None:
    """command-interpreter-spec mentions request_module_assignment."""
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "request_module_assignment" in content


@pytest.mark.unit
def test_command_interpreter_spec_governed_modules_null_for_da() -> None:
    """command-interpreter-spec documents that governed_modules can be null for DA."""
    spec_path = (
        _REPO_ROOT
        / "domain-packs/system/domain-lib/reference/command-interpreter-spec-v1.md"
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "null" in content.lower() and "governed_modules" in content


@pytest.mark.unit
def test_request_module_assignment_schema_exists() -> None:
    """JSON schema exists for request_module_assignment."""
    schema_path = _REPO_ROOT / "standards/admin-command-schemas/request-module-assignment.json"
    assert schema_path.exists()
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert data["title"] == "request_module_assignment"
    assert "schema_version" in data


@pytest.mark.unit
def test_education_module_map_includes_general(registry: DomainRegistry) -> None:
    """Education domain module list includes general-education."""
    modules = registry.list_modules_for_domain("education")
    mod_ids = [m["module_id"] for m in modules]
    assert "domain/edu/general-education/v1" in mod_ids


@pytest.mark.unit
def test_agriculture_module_map_includes_general(registry: DomainRegistry) -> None:
    """Agriculture domain module list includes general-operations."""
    modules = registry.list_modules_for_domain("agriculture")
    mod_ids = [m["module_id"] for m in modules]
    assert "domain/agri/general-operations/v1" in mod_ids


# ── Phase 7: Domain role wiring tests ─────────────────────────


@pytest.mark.unit
def test_check_permission_student_acl_grants_execute() -> None:
    """Student with domain_role='student' passes ACL check on algebra module."""
    from lumina.core.permissions import check_permission, Operation

    # Algebra module: mode=750, group=educators, ACL grants student execute
    module_permissions = {
        "mode": "750",
        "owner": "da_algebra_lead_001",
        "group": "educators",
        "acl": [
            {"role": "operator", "access": "rx", "scope": "evaluation_only"},
            {"domain_role": "student", "access": "x"},
        ],
    }
    domain_roles_config = {
        "roles": [
            {"role_id": "teacher", "default_access": "rwx", "hierarchy_level": 1},
            {"role_id": "student", "default_access": "x", "hierarchy_level": 3},
        ],
    }
    groups_config = {
        "educators": {
            "members": {"domain_roles": ["teacher", "teaching_assistant"]},
        },
    }

    # Student: others bits = 0, but domain_role ACL grants x
    assert check_permission(
        user_id="student_user_1",
        user_role="user",
        module_permissions=module_permissions,
        operation=Operation.EXECUTE,
        domain_role="student",
        domain_roles_config=domain_roles_config,
        groups_config=groups_config,
    )


@pytest.mark.unit
def test_check_permission_student_denied_without_domain_role() -> None:
    """Without domain_role='student', a plain 'user' gets others=0 → denied."""
    from lumina.core.permissions import check_permission, Operation

    module_permissions = {
        "mode": "750",
        "owner": "da_algebra_lead_001",
        "group": "educators",
        "acl": [
            {"domain_role": "student", "access": "x"},
        ],
    }
    groups_config = {
        "educators": {
            "members": {"domain_roles": ["teacher", "teaching_assistant"]},
        },
    }

    # No domain_role → falls to others (0), ACL requires domain_role match
    assert not check_permission(
        user_id="student_user_1",
        user_role="user",
        module_permissions=module_permissions,
        operation=Operation.EXECUTE,
        domain_role=None,
        domain_roles_config=None,
        groups_config=groups_config,
    )


@pytest.mark.unit
def test_check_permission_teacher_gets_group_access() -> None:
    """Teacher in 'educators' group gets group bits (5 = r-x)."""
    from lumina.core.permissions import check_permission, Operation

    module_permissions = {
        "mode": "750",
        "owner": "da_algebra_lead_001",
        "group": "educators",
        "acl": [],
    }
    domain_roles_config = {
        "roles": [
            {"role_id": "teacher", "default_access": "rwx", "hierarchy_level": 1},
        ],
    }
    groups_config = {
        "educators": {
            "members": {"domain_roles": ["teacher", "teaching_assistant"]},
        },
    }

    # Teacher is in educators group → group bits = 5 (r-x)
    assert check_permission(
        user_id="teacher_1",
        user_role="user",
        module_permissions=module_permissions,
        operation=Operation.READ,
        domain_role="teacher",
        domain_roles_config=domain_roles_config,
        groups_config=groups_config,
    )
    assert check_permission(
        user_id="teacher_1",
        user_role="user",
        module_permissions=module_permissions,
        operation=Operation.EXECUTE,
        domain_role="teacher",
        domain_roles_config=domain_roles_config,
        groups_config=groups_config,
    )
    # Teacher's domain_role default_access="rwx" grants write additively,
    # even though group bits (5) don't include write.  This is correct —
    # domain_roles are an additive overlay.
    assert check_permission(
        user_id="teacher_1",
        user_role="user",
        module_permissions=module_permissions,
        operation=Operation.WRITE,
        domain_role="teacher",
        domain_roles_config=domain_roles_config,
        groups_config=groups_config,
    )
    # But WITHOUT domain_role, group bits (5 = r-x) don't include write
    assert not check_permission(
        user_id="teacher_1",
        user_role="user",
        module_permissions=module_permissions,
        operation=Operation.WRITE,
        domain_role=None,
        domain_roles_config=None,
        groups_config=groups_config,
    )


@pytest.mark.unit
def test_domain_authority_always_group_member() -> None:
    """admin is always treated as a group member."""
    from lumina.core.permissions import check_permission, Operation

    module_permissions = {
        "mode": "750",
        "owner": "da_algebra_lead_001",
        "group": "educators",
        "acl": [],
    }

    assert check_permission(
        user_id="some_da",
        user_role="admin",
        module_permissions=module_permissions,
        operation=Operation.READ,
    )
    assert check_permission(
        user_id="some_da",
        user_role="admin",
        module_permissions=module_permissions,
        operation=Operation.EXECUTE,
    )


@pytest.mark.unit
def test_list_domain_rbac_roles_returns_actual_roles(registry: DomainRegistry) -> None:
    """list_domain_rbac_roles returns teacher/student/etc from domain_roles blocks."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "list_domain_rbac_roles",
        "target": "education",
        "params": {"domain_id": "education"},
    }

    original_p = _cfg.PERSISTENCE
    original_r = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    _cfg.DOMAIN_REGISTRY = registry
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "list rbac roles"))
    finally:
        _cfg.PERSISTENCE = original_p
        _cfg.DOMAIN_REGISTRY = original_r

    assert result["operation"] == "list_domain_rbac_roles"
    assert result["domain_id"] == "education"
    # Should have roles from algebra module
    all_roles = result["domain_roles"]
    assert len(all_roles) > 0
    # Collect all role_ids from all modules
    role_ids = set()
    for mod_roles in all_roles.values():
        for r in mod_roles.get("roles", []):
            role_ids.add(r["role_id"])
    assert "teacher" in role_ids
    assert "student" in role_ids


@pytest.mark.unit
def test_assign_domain_role_validates_role_id(registry: DomainRegistry) -> None:
    """assign_domain_role rejects unknown role for a module with defined roles."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    from fastapi import HTTPException
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.get_user.return_value = {"user_id": "u1", "role": "user"}
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "assign_domain_role",
        "target": "u1",
        "params": {
            "user_id": "u1",
            "module_id": "domain/edu/algebra-level-1/v1",
            "domain_role": "janitor",  # not a valid role
        },
    }

    original_p = _cfg.PERSISTENCE
    original_r = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    _cfg.DOMAIN_REGISTRY = registry
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(_execute_admin_operation(user_data, parsed, "assign role"))
        assert exc_info.value.status_code == 422
        assert "janitor" in str(exc_info.value.detail)
    finally:
        _cfg.PERSISTENCE = original_p
        _cfg.DOMAIN_REGISTRY = original_r


@pytest.mark.unit
def test_assign_domain_role_accepts_valid_role(registry: DomainRegistry) -> None:
    """assign_domain_role accepts teacher for the algebra module."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.get_user.return_value = {"user_id": "u1", "role": "user"}
    mock_persistence.update_user_domain_roles = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root"}
    parsed = {
        "operation": "assign_domain_role",
        "target": "u1",
        "params": {
            "user_id": "u1",
            "module_id": "domain/edu/algebra-level-1/v1",
            "domain_role": "teacher",
        },
    }

    original_p = _cfg.PERSISTENCE
    original_r = _cfg.DOMAIN_REGISTRY
    _cfg.PERSISTENCE = mock_persistence
    _cfg.DOMAIN_REGISTRY = registry
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "assign role"))
    finally:
        _cfg.PERSISTENCE = original_p
        _cfg.DOMAIN_REGISTRY = original_r

    assert result["operation"] == "assign_domain_role"
    assert result["domain_role"] == "teacher"


@pytest.mark.unit
def test_dynamic_role_alias_aggregation(registry: DomainRegistry) -> None:
    """_get_domain_role_aliases dynamically aggregates maps_to_system_role."""
    from lumina.api.routes.admin import _get_domain_role_aliases
    from lumina.api import config as _cfg

    original = _cfg.DOMAIN_REGISTRY
    _cfg.DOMAIN_REGISTRY = registry
    try:
        aliases = _get_domain_role_aliases()
    finally:
        _cfg.DOMAIN_REGISTRY = original

    # Should have roles from education domain
    assert "teacher" in aliases
    assert "student" in aliases
    # All should map to system roles
    for role_id, sys_role in aliases.items():
        assert sys_role in {
            "root", "admin", "super_admin", "operator", "half_operator", "user", "guest"
        }, f"{role_id} maps to invalid system role: {sys_role}"


@pytest.mark.unit
def test_invite_pre_assigns_domain_role() -> None:
    """invite_user with intended_domain_role pre-assigns domain roles."""
    from lumina.api.routes.admin import _execute_admin_operation
    from lumina.api import config as _cfg
    import asyncio

    mock_persistence = MagicMock()
    mock_persistence.get_user_by_username.return_value = None
    mock_persistence.create_user = MagicMock()
    mock_persistence.update_user_domain_roles = MagicMock()
    mock_persistence.set_user_invite_token = MagicMock()
    mock_persistence.append_log_record = MagicMock()
    mock_persistence.get_log_ledger_path = MagicMock(return_value="test.jsonl")

    user_data = {"sub": "admin", "role": "root", "username": "admin"}
    parsed = {
        "operation": "invite_user",
        "target": "StudentX",
        "params": {
            "username": "StudentX",
            "role": "user",
            "intended_domain_role": "student",
            "governed_modules": ["domain/edu/algebra-level-1/v1"],
        },
    }

    original = _cfg.PERSISTENCE
    _cfg.PERSISTENCE = mock_persistence
    try:
        result = asyncio.run(_execute_admin_operation(user_data, parsed, "invite student"))
    finally:
        _cfg.PERSISTENCE = original

    assert result["operation"] == "invite_user"
    # Verify update_user_domain_roles was called to pre-assign
    mock_persistence.update_user_domain_roles.assert_called_once()
    call_args = mock_persistence.update_user_domain_roles.call_args
    domain_roles_map = call_args[0][1]
    assert domain_roles_map == {"domain/edu/algebra-level-1/v1": "student"}
