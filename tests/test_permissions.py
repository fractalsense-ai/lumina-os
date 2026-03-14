from __future__ import annotations

import pytest

from lumina.core.permissions import Operation, check_permission, check_permission_or_raise, mode_to_symbolic, parse_octal


BASE_PERMS = {
    "mode": "750",
    "owner": "da_owner_001",
    "group": "domain_authority",
    "acl": [
        {"role": "qa", "access": "rx", "scope": "evaluation_only"},
        {"role": "auditor", "access": "r", "scope": "ctl_only"},
    ],
}


@pytest.mark.unit
def test_parse_octal_valid() -> None:
    assert parse_octal("750") == (7, 5, 0)


@pytest.mark.unit
def test_parse_octal_invalid() -> None:
    with pytest.raises(ValueError):
        parse_octal("88")


@pytest.mark.unit
def test_mode_to_symbolic() -> None:
    assert mode_to_symbolic("750") == "rwxr-x---"


@pytest.mark.unit
def test_root_bypass_grants_any_operation() -> None:
    assert check_permission("any", "root", BASE_PERMS, Operation.WRITE)


@pytest.mark.unit
def test_owner_permissions_applied() -> None:
    assert check_permission("da_owner_001", "domain_authority", BASE_PERMS, Operation.EXECUTE)
    assert check_permission("da_owner_001", "domain_authority", BASE_PERMS, Operation.WRITE)


@pytest.mark.unit
def test_group_permissions_applied() -> None:
    assert check_permission("other_user", "domain_authority", BASE_PERMS, Operation.READ)
    assert check_permission("other_user", "domain_authority", BASE_PERMS, Operation.EXECUTE)
    assert not check_permission("other_user", "domain_authority", BASE_PERMS, Operation.WRITE)


@pytest.mark.unit
def test_others_denied_without_acl() -> None:
    assert not check_permission("u-x", "user", BASE_PERMS, Operation.READ)


@pytest.mark.unit
def test_acl_fallback_grants_when_mode_denies() -> None:
    assert check_permission("qa-1", "qa", BASE_PERMS, Operation.READ)
    assert check_permission("qa-1", "qa", BASE_PERMS, Operation.EXECUTE)
    assert not check_permission("qa-1", "qa", BASE_PERMS, Operation.WRITE)


@pytest.mark.unit
def test_check_permission_or_raise() -> None:
    with pytest.raises(PermissionError):
        check_permission_or_raise("u-x", "user", BASE_PERMS, Operation.EXECUTE)

    check_permission_or_raise("da_owner_001", "domain_authority", BASE_PERMS, Operation.EXECUTE)


# ── Guest role (domain-scoped opt-in) ──────────────────────────

GUEST_ENABLED_PERMS = {
    **BASE_PERMS,
    "guest_access": {"enabled": True, "permissions": "rx"},
}

GUEST_DISABLED_PERMS = {
    **BASE_PERMS,
    "guest_access": {"enabled": False, "permissions": "r"},
}


@pytest.mark.unit
def test_guest_allowed_on_enabled_domain_read() -> None:
    assert check_permission("guest_001", "guest", GUEST_ENABLED_PERMS, Operation.READ)


@pytest.mark.unit
def test_guest_allowed_on_enabled_domain_execute() -> None:
    assert check_permission("guest_001", "guest", GUEST_ENABLED_PERMS, Operation.EXECUTE)


@pytest.mark.unit
def test_guest_denied_write_even_on_enabled_domain() -> None:
    assert not check_permission("guest_001", "guest", GUEST_ENABLED_PERMS, Operation.WRITE)


@pytest.mark.unit
def test_guest_denied_on_disabled_domain() -> None:
    assert not check_permission("guest_001", "guest", GUEST_DISABLED_PERMS, Operation.READ)


@pytest.mark.unit
def test_guest_denied_when_no_guest_access_block() -> None:
    assert not check_permission("guest_001", "guest", BASE_PERMS, Operation.READ)


@pytest.mark.unit
def test_guest_read_only_domain() -> None:
    perms = {**BASE_PERMS, "guest_access": {"enabled": True, "permissions": "r"}}
    assert check_permission("guest_001", "guest", perms, Operation.READ)
    assert not check_permission("guest_001", "guest", perms, Operation.EXECUTE)


# ── Ingest permission (ACL-only) ──────────────────────────────

INGEST_PERMS = {
    **BASE_PERMS,
    "acl": [
        *BASE_PERMS["acl"],
        {"role": "domain_authority", "access": "rwi"},
        {"role": "user", "access": "ri", "scope": "lesson_plans_only"},
    ],
}


@pytest.mark.unit
def test_ingest_granted_via_acl() -> None:
    assert check_permission("da_other", "domain_authority", INGEST_PERMS, Operation.INGEST)


@pytest.mark.unit
def test_ingest_granted_to_flagged_user() -> None:
    assert check_permission("u-1", "user", INGEST_PERMS, Operation.INGEST)


@pytest.mark.unit
def test_ingest_denied_without_acl_entry() -> None:
    assert not check_permission("u-1", "user", BASE_PERMS, Operation.INGEST)


@pytest.mark.unit
def test_ingest_denied_for_guest() -> None:
    assert not check_permission("guest_001", "guest", INGEST_PERMS, Operation.INGEST)


@pytest.mark.unit
def test_root_always_bypasses_ingest() -> None:
    assert check_permission("root_001", "root", BASE_PERMS, Operation.INGEST)
