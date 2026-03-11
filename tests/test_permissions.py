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
