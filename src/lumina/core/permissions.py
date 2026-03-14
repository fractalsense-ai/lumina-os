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


def check_permission(
    user_id: str,
    user_role: str,
    module_permissions: dict[str, Any],
    operation: Operation,
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
    elif user_role == group_role:
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

    return False


def check_permission_or_raise(
    user_id: str,
    user_role: str,
    module_permissions: dict[str, Any],
    operation: Operation,
) -> None:
    """Like :func:`check_permission` but raises ``PermissionError`` on denial."""
    if not check_permission(user_id, user_role, module_permissions, operation):
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
