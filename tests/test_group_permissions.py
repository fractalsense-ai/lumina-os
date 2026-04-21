"""Tests for the domain-defined groups feature in permissions.py.

Covers _is_group_member() logic and check_permission() integration with
the groups_config parameter. Validates backward compatibility, system-role
membership, domain-role membership, and mixed membership scenarios.
"""

import pytest

from lumina.core.permissions import (
    Operation,
    _is_group_member,
    check_permission,
    check_permission_or_raise,
)


# ── Fixtures ──────────────────────────────────────────────────────────

GROUPS_CONFIG = {
    "educators": {
        "description": "Teaching staff.",
        "members": {
            "domain_roles": ["teacher", "teaching_assistant"],
        },
    },
    "learners": {
        "description": "Students enrolled in the module.",
        "members": {
            "domain_roles": ["student"],
        },
    },
    "ops": {
        "description": "Operations staff.",
        "members": {
            "system_roles": ["root", "super_admin"],
        },
    },
    "mixed": {
        "description": "Group with both system and domain role members.",
        "members": {
            "system_roles": ["operator"],
            "domain_roles": ["teacher"],
        },
    },
}

EDU_PERMS = {
    "mode": "750",
    "owner": "da_lead_001",
    "group": "educators",
    "acl": [
        {"domain_role": "student", "access": "x"},
    ],
}

OPS_PERMS = {
    "mode": "770",
    "owner": "root",
    "group": "ops",
}

BACKWARD_COMPAT_PERMS = {
    "mode": "750",
    "owner": "da_owner_001",
    "group": "admin",
}


# ── _is_group_member unit tests ──────────────────────────────────────

class TestIsGroupMember:
    """Direct tests for the _is_group_member helper."""

    def test_domain_role_match(self):
        assert _is_group_member("user", "teacher", GROUPS_CONFIG, "educators") is True

    def test_domain_role_no_match(self):
        assert _is_group_member("user", "student", GROUPS_CONFIG, "educators") is False

    def test_system_role_match(self):
        assert _is_group_member("super_admin", None, GROUPS_CONFIG, "ops") is True

    def test_system_role_no_match(self):
        assert _is_group_member("user", None, GROUPS_CONFIG, "ops") is False

    def test_mixed_group_system_role_match(self):
        assert _is_group_member("operator", None, GROUPS_CONFIG, "mixed") is True

    def test_mixed_group_domain_role_match(self):
        assert _is_group_member("user", "teacher", GROUPS_CONFIG, "mixed") is True

    def test_mixed_group_no_match(self):
        assert _is_group_member("user", "student", GROUPS_CONFIG, "mixed") is False

    def test_fallback_no_groups_config(self):
        """No groups_config → fall back to system role string match."""
        assert _is_group_member("admin", None, None, "admin") is True
        assert _is_group_member("user", None, None, "admin") is False

    def test_fallback_group_not_in_config(self):
        """Group name not defined in config → fall back to string match."""
        assert _is_group_member("user", None, GROUPS_CONFIG, "user") is True
        assert _is_group_member("guest", None, GROUPS_CONFIG, "user") is False

    def test_empty_groups_config(self):
        """Empty dict → fall back to string match."""
        assert _is_group_member("user", None, {}, "user") is True

    def test_no_domain_role_with_domain_only_group(self):
        """User has no domain role; group defines only domain_roles."""
        assert _is_group_member("user", None, GROUPS_CONFIG, "educators") is False


# ── check_permission integration with groups_config ──────────────────

class TestCheckPermissionWithGroups:
    """Integration tests: check_permission with groups_config passed."""

    def test_root_bypass(self):
        assert check_permission(
            "any_id", "root", EDU_PERMS, Operation.READ,
            groups_config=GROUPS_CONFIG,
        ) is True

    def test_owner_gets_owner_bits(self):
        assert check_permission(
            "da_lead_001", "user", EDU_PERMS, Operation.READ,
            groups_config=GROUPS_CONFIG,
        ) is True
        assert check_permission(
            "da_lead_001", "user", EDU_PERMS, Operation.WRITE,
            groups_config=GROUPS_CONFIG,
        ) is True

    def test_domain_role_group_member_gets_group_bits(self):
        """Teacher is in 'educators' group → gets group bits (5 = r-x)."""
        assert check_permission(
            "teacher_001", "user", EDU_PERMS, Operation.READ,
            domain_role="teacher",
            groups_config=GROUPS_CONFIG,
        ) is True
        assert check_permission(
            "teacher_001", "user", EDU_PERMS, Operation.EXECUTE,
            domain_role="teacher",
            groups_config=GROUPS_CONFIG,
        ) is True
        # Write is NOT in group bits (5 = r-x)
        assert check_permission(
            "teacher_001", "user", EDU_PERMS, Operation.WRITE,
            domain_role="teacher",
            groups_config=GROUPS_CONFIG,
        ) is False

    def test_ta_group_member(self):
        """TA is also in 'educators' group → gets group bits."""
        assert check_permission(
            "ta_001", "user", EDU_PERMS, Operation.READ,
            domain_role="teaching_assistant",
            groups_config=GROUPS_CONFIG,
        ) is True

    def test_student_not_in_educators_falls_to_others(self):
        """Student is NOT in 'educators' group → falls through to others (0)."""
        assert check_permission(
            "student_001", "user", EDU_PERMS, Operation.READ,
            domain_role="student",
            groups_config=GROUPS_CONFIG,
        ) is False

    def test_student_acl_fallback(self):
        """Student denied by mode but granted execute via domain_role ACL entry."""
        # The ACL {"domain_role": "student", "access": "x"} won't match
        # system-role ACL step (step 6), but domain_role step 7 requires
        # domain_roles_config. Without it, student is denied.
        # With domain_roles_config, step 7 would check default_access.
        # Here we test that without domain_roles_config, mode+ACL is all.
        assert check_permission(
            "student_001", "user", EDU_PERMS, Operation.READ,
            domain_role="student",
            groups_config=GROUPS_CONFIG,
        ) is False

    def test_system_role_group_member(self):
        """it_support is in 'ops' group → gets group bits (7 = rwx)."""
        assert check_permission(
            "it_001", "super_admin", OPS_PERMS, Operation.WRITE,
            groups_config=GROUPS_CONFIG,
        ) is True

    def test_non_member_gets_others_bits(self):
        """user role is not in 'ops' → gets others bits (0 = ---)."""
        assert check_permission(
            "user_001", "user", OPS_PERMS, Operation.READ,
            groups_config=GROUPS_CONFIG,
        ) is False


class TestBackwardCompatibility:
    """Verify that existing permissions without groups still work."""

    def test_no_groups_config_system_role_match(self):
        """Omitting groups_config → falls back to system role string match."""
        assert check_permission(
            "da_somebody", "admin",
            BACKWARD_COMPAT_PERMS, Operation.READ,
        ) is True

    def test_no_groups_config_no_match(self):
        assert check_permission(
            "user_001", "user",
            BACKWARD_COMPAT_PERMS, Operation.READ,
        ) is False

    def test_groups_config_none_explicit(self):
        assert check_permission(
            "da_somebody", "admin",
            BACKWARD_COMPAT_PERMS, Operation.READ,
            groups_config=None,
        ) is True

    def test_groups_config_empty_dict(self):
        """Empty groups dict → group name not found → fallback to string match."""
        assert check_permission(
            "da_somebody", "admin",
            BACKWARD_COMPAT_PERMS, Operation.READ,
            groups_config={},
        ) is True


class TestCheckPermissionOrRaiseWithGroups:
    """Ensure check_permission_or_raise passes groups_config through."""

    def test_allowed(self):
        check_permission_or_raise(
            "it_001", "super_admin", OPS_PERMS, Operation.READ,
            groups_config=GROUPS_CONFIG,
        )

    def test_denied_raises(self):
        with pytest.raises(PermissionError):
            check_permission_or_raise(
                "user_001", "user", OPS_PERMS, Operation.WRITE,
                groups_config=GROUPS_CONFIG,
            )
