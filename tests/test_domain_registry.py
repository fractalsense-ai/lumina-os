"""Unit tests for DomainRegistry.resolve_default_for_user().

These tests exercise the role-based default domain resolution logic
introduced to route system-level operators to the system domain instead
of the global default_domain (education), and the unauthenticated_domain
feature that separates anonymous landing from the authenticated fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lumina.core.domain_registry import DomainRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]

# -- Fixtures -------------------------------------------------


@pytest.fixture
def registry() -> DomainRegistry:
    """Load DomainRegistry in multi-domain mode from the real registry YAML."""
    return DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path="cfg/domain-registry.yaml",
        # No load_runtime_context_fn needed — we only test resolve_default_for_user
    )


# -- resolve_default_for_user() --------------------------------


@pytest.mark.unit
def test_unauthenticated_user_returns_global_default(registry: DomainRegistry) -> None:
    """None user (unauthenticated) -> unauthenticated_domain (education per real config)."""
    result = registry.resolve_default_for_user(None)
    assert result == "education"


@pytest.mark.unit
def test_root_role_returns_system(registry: DomainRegistry) -> None:
    """root role -> system domain (via role_defaults)."""
    user = {"sub": "root_001", "role": "root", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "system"


@pytest.mark.unit
def test_it_support_role_returns_system(registry: DomainRegistry) -> None:
    """it_support role -> system domain (via role_defaults)."""
    user = {"sub": "its_001", "role": "it_support", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "system"


@pytest.mark.unit
def test_qa_role_returns_global_default(registry: DomainRegistry) -> None:
    """qa role is not in role_defaults -> falls through to global default (education)."""
    user = {"sub": "qa_001", "role": "qa", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "education"


@pytest.mark.unit
def test_auditor_role_returns_global_default(registry: DomainRegistry) -> None:
    """auditor role is not in role_defaults -> falls through to global default (education)."""
    user = {"sub": "aud_001", "role": "auditor", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "education"


@pytest.mark.unit
def test_user_role_returns_global_default(registry: DomainRegistry) -> None:
    """user role falls through to global default (education)."""
    user = {"sub": "usr_001", "role": "user", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "education"


@pytest.mark.unit
def test_domain_authority_with_edu_module_returns_education(registry: DomainRegistry) -> None:
    """domain_authority with a domain/edu/... module -> education domain."""
    user = {
        "sub": "da_001",
        "role": "domain_authority",
        "governed_modules": ["domain/edu/algebra-level-1/v1"],
    }
    assert registry.resolve_default_for_user(user) == "education"


@pytest.mark.unit
def test_domain_authority_with_agri_module_returns_agriculture(registry: DomainRegistry) -> None:
    """domain_authority with a domain/agri/... module -> agriculture domain."""
    user = {
        "sub": "da_agri_001",
        "role": "domain_authority",
        "governed_modules": ["domain/agri/operations-level-1/v1"],
    }
    assert registry.resolve_default_for_user(user) == "agriculture"


@pytest.mark.unit
def test_domain_authority_empty_governed_modules_returns_global_default(
    registry: DomainRegistry,
) -> None:
    """domain_authority with empty governed_modules cannot infer prefix -> global default."""
    user = {"sub": "da_002", "role": "domain_authority", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "education"


@pytest.mark.unit
def test_domain_authority_unknown_prefix_returns_global_default(
    registry: DomainRegistry,
) -> None:
    """domain_authority with an unregistered module prefix -> global default."""
    user = {
        "sub": "da_003",
        "role": "domain_authority",
        "governed_modules": ["domain/zzz/unknown-module/v1"],
    }
    assert registry.resolve_default_for_user(user) == "education"


@pytest.mark.unit
def test_domain_authority_uses_first_governed_module_only(registry: DomainRegistry) -> None:
    """When multiple governed_modules are present, only the first is used for inference."""
    user = {
        "sub": "da_004",
        "role": "domain_authority",
        "governed_modules": [
            "domain/edu/algebra-level-1/v1",
            "domain/agri/operations-level-1/v1",
        ],
    }
    assert registry.resolve_default_for_user(user) == "education"


# -- Single-domain mode: resolve_default_for_user() still works -----------


@pytest.mark.unit
def test_single_domain_mode_always_returns_default(tmp_path: Path) -> None:
    """In single-domain mode, resolve_default_for_user returns the single domain regardless of role."""
    # Point at a real runtime config so the registry initialises without error
    reg = DomainRegistry(
        repo_root=_REPO_ROOT,
        single_config_path="domain-packs/education/cfg/runtime-config.yaml",
    )
    for role in ("root", "it_support", "qa", "auditor", "user"):
        result = reg.resolve_default_for_user({"sub": "u", "role": role, "governed_modules": []})
        assert result == "_default", f"Expected '_default' for role {role!r}, got {result!r}"


# -- unauthenticated_domain ------------------------------------


@pytest.mark.unit
def test_unauthenticated_domain_used_for_none_user(tmp_path: Path) -> None:
    """When unauthenticated_domain is set, None user routes to it (not default_domain)."""
    # Build a minimal in-memory registry YAML in a temp dir
    import yaml

    # Reuse real runtime configs so the path-existence check passes
    reg_data = {
        "unauthenticated_domain": "education",
        "default_domain": "education",
        "role_defaults": {"root": "system", "it_support": "system"},
        "domains": {
            "education": {
                "runtime_config_path": "domain-packs/education/cfg/runtime-config.yaml",
                "label": "Education",
            },
            "system": {
                "runtime_config_path": "domain-packs/system/cfg/runtime-config.yaml",
                "label": "System",
            },
        },
    }
    reg_file = tmp_path / "registry.yaml"
    reg_file.write_text(yaml.safe_dump(reg_data), encoding="utf-8")
    reg = DomainRegistry(
        repo_root=_REPO_ROOT,
        registry_path=str(reg_file.relative_to(_REPO_ROOT)) if reg_file.is_relative_to(_REPO_ROOT) else str(reg_file),
    )
    # Override _repo_root so relative path resolves correctly from tmp_path
    reg._repo_root = _REPO_ROOT

    assert reg.resolve_default_for_user(None) == "education"


@pytest.mark.unit
def test_unauthenticated_domain_separate_from_default(tmp_path: Path) -> None:
    """unauthenticated_domain can differ from default_domain; None user gets unauthenticated_domain."""
    import yaml

    reg_data = {
        "unauthenticated_domain": "agriculture",
        "default_domain": "education",
        "domains": {
            "education": {
                "runtime_config_path": "domain-packs/education/cfg/runtime-config.yaml",
                "label": "Education",
            },
            "agriculture": {
                "runtime_config_path": "domain-packs/agriculture/cfg/runtime-config.yaml",
                "label": "Agriculture",
            },
            "system": {
                "runtime_config_path": "domain-packs/system/cfg/runtime-config.yaml",
                "label": "System",
            },
        },
    }
    reg_file = tmp_path / "registry.yaml"
    reg_file.write_text(yaml.safe_dump(reg_data), encoding="utf-8")
    reg = DomainRegistry(repo_root=_REPO_ROOT, registry_path=str(reg_file))

    # Anonymous -> unauthenticated_domain
    assert reg.resolve_default_for_user(None) == "agriculture"
    # Authenticated user with no role_default -> default_domain
    assert reg.resolve_default_for_user({"sub": "u", "role": "user", "governed_modules": []}) == "education"


@pytest.mark.unit
def test_unauthenticated_domain_absent_falls_back_to_default(tmp_path: Path) -> None:
    """When unauthenticated_domain is absent, None user falls back to default_domain."""
    import yaml

    reg_data = {
        "default_domain": "education",
        "domains": {
            "education": {
                "runtime_config_path": "domain-packs/education/cfg/runtime-config.yaml",
                "label": "Education",
            },
        },
    }
    reg_file = tmp_path / "registry.yaml"
    reg_file.write_text(yaml.safe_dump(reg_data), encoding="utf-8")
    reg = DomainRegistry(repo_root=_REPO_ROOT, registry_path=str(reg_file))

    assert reg.resolve_default_for_user(None) == "education"


@pytest.mark.unit
def test_unauthenticated_domain_invalid_raises(tmp_path: Path) -> None:
    """unauthenticated_domain referencing an unknown domain raises RuntimeError at load time."""
    import yaml

    reg_data = {
        "unauthenticated_domain": "nonexistent",
        "default_domain": "education",
        "domains": {
            "education": {
                "runtime_config_path": "domain-packs/education/cfg/runtime-config.yaml",
                "label": "Education",
            },
        },
    }
    reg_file = tmp_path / "registry.yaml"
    reg_file.write_text(yaml.safe_dump(reg_data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unauthenticated_domain"):
        DomainRegistry(repo_root=_REPO_ROOT, registry_path=str(reg_file))


@pytest.mark.unit
def test_real_registry_unauthenticated_routes_to_education(registry: DomainRegistry) -> None:
    """Integration: real cfg/domain-registry.yaml unauthenticated_domain resolves to education."""
    assert registry.resolve_default_for_user(None) == "education"


@pytest.mark.unit
def test_real_registry_root_still_routes_to_system(registry: DomainRegistry) -> None:
    """Regression: root role still resolves to system after unauthenticated_domain addition."""
    user = {"sub": "root_001", "role": "root", "governed_modules": []}
    assert registry.resolve_default_for_user(user) == "system"
