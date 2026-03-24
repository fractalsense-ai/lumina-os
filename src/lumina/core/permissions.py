"""
Project Lumina — chmod-style Permission Checker

Evaluates module access by parsing the octal ``permissions.mode`` from
a domain-physics document and checking the requesting user's role and
identity against owner/group/others categories.

See specs/rbac-spec-v1.md for the full specification.
"""

from __future__ import annotations

from enum import IntFlag
from typing import Any


class Operation(IntFlag):
    """Permission bits matching UNIX rwx semantics.

    INGEST is an ACL-only permission (not encoded in octal mode bits).
    """

    READ = 4
    WRITE = 2
    EXECUTE = 1
    INGEST = 8


# Canonical role set (matches auth.VALID_ROLES)
_VALID_ROLES: frozenset[str] = frozenset(
    {"root", "domain_authority", "it_support", "qa", "auditor", "user", "guest"}
)


def parse_octal(mode: str) -> tuple[int, int, int]:
    """Parse a 3-digit octal mode string into (owner, group, others) bit tuples.

    >>> parse_octal("750")
    (7, 5, 0)
    """
    if not isinstance(mode, str) or len(mode) != 3 or not all(c in "01234567" for c in mode):
        raise ValueError(f"Invalid octal mode: {mode!r}")
    return int(mode[0]), int(mode[1]), int(mode[2])


def _is_group_member(
    user_role: str,
    domain_role: str | None,
    groups_config: dict[str, Any] | None,
    group_name: str,
) -> bool:
    """Check whether the user is a member of the named group.

    Resolution order:
    1. If *groups_config* contains *group_name*, check its ``members``
       block against the user's system role and optional domain role.
    2. Fallback: if there is no groups block or the group name is not
       defined in it, match literally against the user's system role.
       This preserves backward compatibility with modules that set
       ``permissions.group`` to a system role name.
    """
    if groups_config and group_name in groups_config:
        members = groups_config[group_name].get("members", {})
        sys_roles = members.get("system_roles", [])
        if user_role in sys_roles:
            return True
        dom_roles = members.get("domain_roles", [])
        if domain_role and domain_role in dom_roles:
            return True
        return False
    # Backward compat: no groups block or group not listed — fall back to
    # direct system-role string comparison.
    return user_role == group_name


def check_permission(
    user_id: str,
    user_role: str,
    module_permissions: dict[str, Any],
    operation: Operation,
    *,
    domain_role: str | None = None,
    domain_roles_config: dict[str, Any] | None = None,
    groups_config: dict[str, Any] | None = None,
) -> bool:
    """Evaluate whether a user may perform *operation* on a module.

    Parameters
    ----------
    user_id:
        Pseudonymous ID of the requesting user (from JWT ``sub`` claim).
    user_role:
        Canonical role ID of the requesting user (from JWT ``role`` claim).
    module_permissions:
        The ``permissions`` block from the module's domain-physics document.
        Expected keys: ``mode``, ``owner``, ``group``, and optionally ``acl``.
    operation:
        The :class:`Operation` being requested.
    domain_role:
        Optional domain-scoped role ID for the requesting user in this
        module (from the JWT ``domain_roles`` claim).
    domain_roles_config:
        Optional ``domain_roles`` block from the module's domain-physics
        document.  Required when *domain_role* is provided.
    groups_config:
        Optional ``groups`` block from the module's domain-physics
        document.  Maps group names to membership criteria.

    Returns
    -------
    bool
        ``True`` if access is granted, ``False`` otherwise.
    """
    # Step 1: root always bypasses
    if user_role == "root":
        return True

    # Step 2: INGEST is ACL-only — never in octal mode bits
    if operation == Operation.INGEST:
        acl = module_permissions.get("acl")
        if isinstance(acl, list):
            for entry in acl:
                if not isinstance(entry, dict):
                    continue
                if entry.get("role") != user_role:
                    continue
                if "i" in entry.get("access", ""):
                    return True
        return False

    # Step 3: guest role — domain-scoped opt-in via guest_access block
    if user_role == "guest":
        guest_access = module_permissions.get("guest_access")
        if not isinstance(guest_access, dict) or not guest_access.get("enabled"):
            return False
        allowed = guest_access.get("permissions", "")
        op_char = {
            Operation.READ: "r",
            Operation.WRITE: "w",
            Operation.EXECUTE: "x",
        }.get(operation, "")
        return op_char in allowed

    mode_str = module_permissions.get("mode", "000")
    owner_id = module_permissions.get("owner", "")
    group_role = module_permissions.get("group", "")

    owner_bits, group_bits, others_bits = parse_octal(mode_str)

    # Step 4: determine category
    if user_id == owner_id:
        bits = owner_bits
    elif _is_group_member(user_role, domain_role, groups_config, group_role):
        bits = group_bits
    else:
        bits = others_bits

    # Step 5: check mode bits
    if bits & operation:
        return True

    # Step 6: check extended ACL
    acl = module_permissions.get("acl")
    if isinstance(acl, list):
        op_char = {
            Operation.READ: "r",
            Operation.WRITE: "w",
            Operation.EXECUTE: "x",
            Operation.INGEST: "i",
        }.get(operation, "")
        for entry in acl:
            if not isinstance(entry, dict):
                continue
            if entry.get("role") != user_role:
                continue
            access = entry.get("access", "")
            if op_char in access:
                return True

    # Step 7: check domain role (additive overlay)
    if domain_role and domain_roles_config:
        op_char = {
            Operation.READ: "r",
            Operation.WRITE: "w",
            Operation.EXECUTE: "x",
            Operation.INGEST: "i",
        }.get(operation, "")
        if op_char and _check_domain_role(
            domain_role, op_char, domain_roles_config, module_permissions
        ):
            return True

    return False


def _check_domain_role(
    domain_role: str,
    op_char: str,
    domain_roles_config: dict[str, Any],
    module_permissions: dict[str, Any],
) -> bool:
    """Check whether a domain role grants the requested operation.

    Looks up *domain_role* in the ``domain_roles_config`` block and checks:
    1. The role's ``default_access`` string.
    2. The ``role_acl`` entries in the domain_roles_config.
    3. Any ``domain_role``-keyed entries in the main ``permissions.acl``.
    """
    roles = domain_roles_config.get("roles")
    if not isinstance(roles, list):
        return False

    # Find the role definition
    role_def: dict[str, Any] | None = None
    for r in roles:
        if isinstance(r, dict) and r.get("role_id") == domain_role:
            role_def = r
            break
    if role_def is None:
        return False

    # Check default_access
    if op_char in role_def.get("default_access", ""):
        return True

    # Check role_acl in domain_roles_config
    role_acl = domain_roles_config.get("role_acl")
    if isinstance(role_acl, list):
        for entry in role_acl:
            if not isinstance(entry, dict):
                continue
            if entry.get("domain_role") != domain_role:
                continue
            if op_char in entry.get("access", ""):
                return True

    # Check main permissions.acl for domain_role-keyed entries
    acl = module_permissions.get("acl")
    if isinstance(acl, list):
        for entry in acl:
            if not isinstance(entry, dict):
                continue
            if entry.get("domain_role") != domain_role:
                continue
            if op_char in entry.get("access", ""):
                return True

    return False


def check_permission_or_raise(
    user_id: str,
    user_role: str,
    module_permissions: dict[str, Any],
    operation: Operation,
    *,
    domain_role: str | None = None,
    domain_roles_config: dict[str, Any] | None = None,
    groups_config: dict[str, Any] | None = None,
) -> None:
    """Like :func:`check_permission` but raises ``PermissionError`` on denial."""
    if not check_permission(
        user_id,
        user_role,
        module_permissions,
        operation,
        domain_role=domain_role,
        domain_roles_config=domain_roles_config,
        groups_config=groups_config,
    ):
        op_name = operation.name or str(operation)
        raise PermissionError(
            f"Access denied: {user_role}:{user_id} lacks {op_name} on module"
        )


def mode_to_symbolic(mode: str) -> str:
    """Convert a 3-digit octal mode to symbolic rwx notation.

    >>> mode_to_symbolic("750")
    'rwxr-x---'
    """
    owner_bits, group_bits, others_bits = parse_octal(mode)
    parts: list[str] = []
    for bits in (owner_bits, group_bits, others_bits):
        parts.append("r" if bits & 4 else "-")
        parts.append("w" if bits & 2 else "-")
        parts.append("x" if bits & 1 else "-")
    return "".join(parts)
