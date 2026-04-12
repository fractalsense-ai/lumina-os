"""
audit_scanner.py — Static verification that state-mutating endpoints are guarded.

Walks all route modules under ``src/lumina/api/routes/`` and checks that
every endpoint listed in the *state-mutating registry* carries the
``@requires_log_commit`` decorator (detected via the ``_requires_log_commit``
attribute set by :func:`lumina.system_log.commit_guard.requires_log_commit`).

Can be run as:
  python -m lumina.system_log.audit_scanner
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("lumina.audit_scanner")

# ── Registry of endpoints that MUST be guarded ──────────────────
# Keys are module names (relative to lumina.api.routes), values are sets
# of function names that must have @requires_log_commit.
STATE_MUTATING_ENDPOINTS: dict[str, set[str]] = {
    "auth": {
        "register",
        "update_user",
        "delete_user",
        "revoke_token",
        "password_reset",
        "invite_user",
        "setup_password",
    },
    "staging": {
        "create_staged_file",
        "approve_staged_file",
        "reject_staged_file",
    },
    "ingestion": {
        "ingest_commit",
    },
    "domain": {
        "domain_pack_commit",
        "update_domain_physics",
        "close_session",
    },
    "domain_roles": {
        "assign_domain_role",
        "revoke_domain_role",
    },
    "admin": {
        "manifest_regen",
        "admin_command",
        "admin_command_resolve",
    },
    "chat": {
        "chat",
    },
}


def _has_guard_marker(fn: Any) -> bool:
    """Return True if *fn* has the ``_requires_log_commit`` attribute."""
    return getattr(fn, "_requires_log_commit", False) is True


def scan_modules() -> dict[str, list[str]]:
    """Scan route modules and return a dict of unguarded endpoints.

    Returns a mapping ``{module_name: [fn_name, ...]}`` for every
    state-mutating function that is **missing** the guard decorator.
    Empty dict means all endpoints are properly guarded.
    """
    unguarded: dict[str, list[str]] = {}

    for module_name, expected_fns in STATE_MUTATING_ENDPOINTS.items():
        full_module = f"lumina.api.routes.{module_name}"
        try:
            mod = importlib.import_module(full_module)
        except ImportError as exc:
            log.warning("Could not import %s: %s", full_module, exc)
            unguarded[module_name] = sorted(expected_fns)
            continue

        missing: list[str] = []
        for fn_name in sorted(expected_fns):
            fn = getattr(mod, fn_name, None)
            if fn is None:
                log.warning("Function %s.%s not found", full_module, fn_name)
                missing.append(fn_name)
                continue
            if not _has_guard_marker(fn):
                missing.append(fn_name)

        if missing:
            unguarded[module_name] = missing

    return unguarded


def scan_source_ast(routes_dir: Path | None = None) -> dict[str, list[str]]:
    """AST-based scan that does not require importing route modules.

    Parses each route module's source and checks that every registered
    state-mutating function is decorated with ``@requires_log_commit``.
    For modules extracted into service packages the scanner follows the
    canonical source mapping automatically.
    """
    if routes_dir is None:
        routes_dir = Path(__file__).resolve().parent.parent / "api" / "routes"

    # Extracted service modules: route stub → canonical source path.
    services_root = routes_dir.parent.parent / "services"
    _service_source: dict[str, Path] = {
        "auth": services_root / "auth" / "routes.py",
        "staging": services_root / "ingestion" / "staging_routes.py",
        "ingestion": services_root / "ingestion" / "routes.py",
        "domain": services_root / "domain" / "routes.py",
        "domain_roles": services_root / "domain" / "roles_routes.py",
    }

    unguarded: dict[str, list[str]] = {}

    for module_name, expected_fns in STATE_MUTATING_ENDPOINTS.items():
        # Prefer the service package source when available.
        source_file = _service_source.get(module_name)
        if source_file is None or not source_file.exists():
            source_file = routes_dir / f"{module_name}.py"
        if not source_file.exists():
            log.warning("Source file %s not found", source_file)
            unguarded[module_name] = sorted(expected_fns)
            continue

        source = source_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(source_file))
        except SyntaxError as exc:
            log.warning("SyntaxError in %s: %s", source_file, exc)
            unguarded[module_name] = sorted(expected_fns)
            continue

        decorated_fns: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                dec_name: str | None = None
                if isinstance(dec, ast.Name):
                    dec_name = dec.id
                elif isinstance(dec, ast.Attribute):
                    dec_name = dec.attr
                if dec_name == "requires_log_commit":
                    decorated_fns.add(node.name)
                    break

        missing = sorted(expected_fns - decorated_fns)
        if missing:
            unguarded[module_name] = missing

    return unguarded


def print_report(unguarded: dict[str, list[str]]) -> None:
    """Pretty-print the audit report to stdout."""
    if not unguarded:
        print("✅  All state-mutating endpoints are guarded with @requires_log_commit")
        return

    total = sum(len(fns) for fns in unguarded.values())
    print(f"⚠️  {total} unguarded endpoint(s) detected:\n")
    for module_name, fns in sorted(unguarded.items()):
        for fn_name in fns:
            print(f"  lumina.api.routes.{module_name}.{fn_name}")
    print()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    mode = "ast"
    if "--runtime" in sys.argv:
        mode = "runtime"

    if mode == "ast":
        result = scan_source_ast()
    else:
        result = scan_modules()

    print_report(result)
    sys.exit(1 if result else 0)
