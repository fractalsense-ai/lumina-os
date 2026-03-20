"""Tests for Phase 3: State-Change Commit Enforcement.

Verifies:
  1. commit_guard.py — @requires_log_commit decorator + notify_log_commit()
  2. audit_scanner.py — AST-based verification that all state-mutating endpoints
     are decorated with @requires_log_commit
  3. Persistence adapter integration — notify_log_commit() called on log writes
  4. Nightcycle proposal resolve now writes a System Log record
"""

from __future__ import annotations

import asyncio
import ast
import contextvars
import importlib
import json
import os
import sys
import textwrap
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────
# Imports under test
# ─────────────────────────────────────────────────────────────

from lumina.system_log.commit_guard import (
    LogCommitMissing,
    _log_commit_signal,
    is_commit_pending,
    is_commit_satisfied,
    notify_log_commit,
    requires_log_commit,
)

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "lumina"
ROUTES_DIR = SRC_ROOT / "api" / "routes"


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════
# 1. Unit tests for requires_log_commit decorator
# ═════════════════════════════════════════════════════════════


class TestRequiresLogCommit:
    """Core decorator behaviour tests."""

    def test_passes_when_log_committed(self):
        """Endpoint that calls notify_log_commit() should pass."""

        @requires_log_commit
        async def ok_endpoint():
            notify_log_commit()
            return {"status": "ok"}

        result = _run(ok_endpoint())
        assert result == {"status": "ok"}

    def test_raises_when_no_log_committed(self):
        """Endpoint that does NOT call notify should raise LogCommitMissing."""

        @requires_log_commit
        async def bad_endpoint():
            return {"status": "ok"}

        with pytest.raises(LogCommitMissing, match="bad_endpoint"):
            _run(bad_endpoint())

    def test_no_check_on_exception(self):
        """If the endpoint raises, the guard should NOT fire."""

        @requires_log_commit
        async def failing_endpoint():
            raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            _run(failing_endpoint())

    def test_context_isolation(self):
        """Nested/sequential calls should not bleed state."""

        @requires_log_commit
        async def ep1():
            notify_log_commit()
            return "a"

        @requires_log_commit
        async def ep2():
            notify_log_commit()
            return "b"

        assert _run(ep1()) == "a"
        assert _run(ep2()) == "b"

    def test_context_resets_after_failure(self):
        """After a LogCommitMissing, the context vars should be clean."""

        @requires_log_commit
        async def bad():
            return "x"

        with pytest.raises(LogCommitMissing):
            _run(bad())

        # Context should be clean now
        assert not is_commit_pending()
        assert not is_commit_satisfied()

    def test_context_resets_after_endpoint_exception(self):
        """After an endpoint raises, context should be clean."""

        @requires_log_commit
        async def exploding():
            raise TypeError("boom")

        with pytest.raises(TypeError, match="boom"):
            _run(exploding())

        assert not is_commit_pending()
        assert not is_commit_satisfied()

    def test_marker_attribute(self):
        """Decorated functions should have _requires_log_commit=True."""

        @requires_log_commit
        async def ep():
            notify_log_commit()
            return True

        assert getattr(ep, "_requires_log_commit", False) is True

    def test_preserves_function_name(self):
        """Decorator should preserve __name__."""

        @requires_log_commit
        async def my_special_endpoint():
            notify_log_commit()
            return 1

        assert my_special_endpoint.__name__ == "my_special_endpoint"

    def test_passes_args_through(self):
        """Decorator should forward positional and keyword args."""

        @requires_log_commit
        async def ep_with_args(a, b, *, c=3):
            notify_log_commit()
            return a + b + c

        assert _run(ep_with_args(1, 2, c=10)) == 13

    def test_multiple_notifies_ok(self):
        """Calling notify_log_commit() multiple times is harmless."""

        @requires_log_commit
        async def ep():
            notify_log_commit()
            notify_log_commit()
            notify_log_commit()
            return "ok"

        assert _run(ep()) == "ok"


# ═════════════════════════════════════════════════════════════
# 2. Unit tests for notify_log_commit() outside guard context
# ═════════════════════════════════════════════════════════════


class TestNotifyOutsideGuard:
    """notify_log_commit() should be harmless outside a guarded endpoint."""

    def test_no_error_outside_guard(self):
        notify_log_commit()  # should not raise

    def test_is_commit_pending_default(self):
        assert not is_commit_pending()

    def test_is_commit_satisfied_default(self):
        assert not is_commit_satisfied()


# ═════════════════════════════════════════════════════════════
# 3. Persistence adapter integration
# ═════════════════════════════════════════════════════════════


class TestPersistenceNotification:
    """Verify persistence adapters call notify_log_commit()."""

    def test_null_adapter_notifies_on_append_log_record(self):
        from lumina.persistence.adapter import NullPersistenceAdapter

        adapter = NullPersistenceAdapter()

        @requires_log_commit
        async def ep():
            adapter.append_log_record("test-session", {"record_type": "test"})
            return "done"

        result = _run(ep())
        assert result == "done"

    def test_null_adapter_notifies_on_append_system_log_record(self):
        from lumina.persistence.adapter import NullPersistenceAdapter

        adapter = NullPersistenceAdapter()

        @requires_log_commit
        async def ep():
            adapter.append_system_log_record({"record_type": "test"})
            return "done"

        result = _run(ep())
        assert result == "done"

    def test_filesystem_adapter_notifies(self, tmp_path):
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter

        adapter = FilesystemPersistenceAdapter(tmp_path, tmp_path / "logs")

        @requires_log_commit
        async def ep():
            adapter.append_log_record("sess1", {"record_type": "TraceEvent", "record_id": "r1"})
            return "ok"

        result = _run(ep())
        assert result == "ok"

    def test_filesystem_adapter_system_log_notifies(self, tmp_path):
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter

        adapter = FilesystemPersistenceAdapter(tmp_path, tmp_path / "logs")

        @requires_log_commit
        async def ep():
            adapter.append_system_log_record({"record_type": "CommitmentRecord", "record_id": "r1"})
            return "ok"

        result = _run(ep())
        assert result == "ok"


# ═════════════════════════════════════════════════════════════
# 4. AST-based audit scanner tests
# ═════════════════════════════════════════════════════════════


class TestAuditScannerAST:
    """Verify that the AST scanner detects all decorated endpoints."""

    def test_all_state_mutating_endpoints_guarded(self):
        """The audit scanner should find ZERO unguarded endpoints."""
        from lumina.system_log.audit_scanner import scan_source_ast

        unguarded = scan_source_ast(ROUTES_DIR)
        if unguarded:
            lines = []
            for mod, fns in sorted(unguarded.items()):
                for fn in fns:
                    lines.append(f"  lumina.api.routes.{mod}.{fn}")
            pytest.fail(
                f"Unguarded state-mutating endpoints:\n" + "\n".join(lines)
            )

    def test_scanner_detects_missing_decorator(self, tmp_path):
        """Scanner should flag a function that lacks the decorator."""
        route_file = tmp_path / "test_route.py"
        route_file.write_text(textwrap.dedent("""\
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/test")
            async def my_endpoint():
                pass
        """), encoding="utf-8")

        from lumina.system_log.audit_scanner import scan_source_ast, STATE_MUTATING_ENDPOINTS

        # Temporarily inject a test entry
        original = dict(STATE_MUTATING_ENDPOINTS)
        STATE_MUTATING_ENDPOINTS["test_route"] = {"my_endpoint"}
        try:
            unguarded = scan_source_ast(tmp_path)
            assert "test_route" in unguarded
            assert "my_endpoint" in unguarded["test_route"]
        finally:
            STATE_MUTATING_ENDPOINTS.clear()
            STATE_MUTATING_ENDPOINTS.update(original)

    def test_scanner_passes_decorated_function(self, tmp_path):
        """Scanner should accept a properly decorated function."""
        route_file = tmp_path / "test_route.py"
        route_file.write_text(textwrap.dedent("""\
            from fastapi import APIRouter
            from lumina.system_log.commit_guard import requires_log_commit
            router = APIRouter()

            @router.post("/test")
            @requires_log_commit
            async def my_endpoint():
                pass
        """), encoding="utf-8")

        from lumina.system_log.audit_scanner import scan_source_ast, STATE_MUTATING_ENDPOINTS

        original = dict(STATE_MUTATING_ENDPOINTS)
        STATE_MUTATING_ENDPOINTS["test_route"] = {"my_endpoint"}
        try:
            unguarded = scan_source_ast(tmp_path)
            assert "test_route" not in unguarded
        finally:
            STATE_MUTATING_ENDPOINTS.clear()
            STATE_MUTATING_ENDPOINTS.update(original)


# ═════════════════════════════════════════════════════════════
# 5. Verify decorator is present via source inspection
# ═════════════════════════════════════════════════════════════


_EXPECTED_DECORATED = {
    "auth.py": [
        "register", "update_user", "delete_user", "revoke_token",
        "password_reset", "invite_user", "setup_password",
    ],
    "staging.py": [
        "create_staged_file", "approve_staged_file", "reject_staged_file",
    ],
    "ingestion.py": ["ingest_commit"],
    "domain.py": ["domain_pack_commit", "update_domain_physics", "close_session"],
    "domain_roles.py": ["assign_domain_role", "revoke_domain_role"],
    "admin.py": [
        "resolve_escalation", "manifest_regen",
        "admin_command", "admin_command_resolve",
    ],
    "chat.py": ["chat"],
    "nightcycle.py": ["nightcycle_resolve_proposal"],
}


class TestDecoratorPresenceInSource:
    """Parse each route file and verify the expected functions have
    ``@requires_log_commit`` in their decorator list."""

    @pytest.mark.parametrize(
        "filename,expected_fns",
        list(_EXPECTED_DECORATED.items()),
        ids=list(_EXPECTED_DECORATED.keys()),
    )
    def test_functions_have_decorator(self, filename, expected_fns):
        source_file = ROUTES_DIR / filename
        assert source_file.exists(), f"{source_file} not found"

        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))

        decorated: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                dec_name = None
                if isinstance(dec, ast.Name):
                    dec_name = dec.id
                elif isinstance(dec, ast.Attribute):
                    dec_name = dec.attr
                if dec_name == "requires_log_commit":
                    decorated.add(node.name)

        for fn_name in expected_fns:
            assert fn_name in decorated, (
                f"{filename}::{fn_name} is missing @requires_log_commit"
            )


# ═════════════════════════════════════════════════════════════
# 6. Verify all route files import commit_guard
# ═════════════════════════════════════════════════════════════


_ROUTE_FILES_WITH_GUARD = [
    "auth.py", "staging.py", "ingestion.py", "domain.py",
    "domain_roles.py", "admin.py", "chat.py", "nightcycle.py",
]


class TestRouteImports:
    @pytest.mark.parametrize("filename", _ROUTE_FILES_WITH_GUARD)
    def test_imports_requires_log_commit(self, filename):
        source = (ROUTES_DIR / filename).read_text(encoding="utf-8")
        assert "requires_log_commit" in source, (
            f"{filename} does not import requires_log_commit"
        )


# ═════════════════════════════════════════════════════════════
# 7. Nightcycle proposal resolve now writes a log record
# ═════════════════════════════════════════════════════════════


class TestNightcycleResolveLogsRecord:
    """Verify the nightcycle proposal resolve endpoint writes a commitment record."""

    def test_nightcycle_route_writes_log_record(self):
        """Source of nightcycle.py should call append_log_record after resolve_proposal."""
        source = (ROUTES_DIR / "nightcycle.py").read_text(encoding="utf-8")
        # The function should contain both resolve_proposal and append_log_record
        assert "resolve_proposal" in source
        assert "append_log_record" in source
        assert "nightcycle_proposal_resolution" in source

    def test_nightcycle_route_builds_commitment_record(self):
        """Source should call build_commitment_record with nightcycle_proposal_resolution."""
        source = (ROUTES_DIR / "nightcycle.py").read_text(encoding="utf-8")
        assert "build_commitment_record" in source


# ═════════════════════════════════════════════════════════════
# 8. Register endpoint now writes a log record
# ═════════════════════════════════════════════════════════════


class TestRegisterLogsRecord:
    """Verify the register endpoint writes a user_registered trace event."""

    def test_register_writes_log_record(self):
        source = (ROUTES_DIR / "auth.py").read_text(encoding="utf-8")
        assert "user_registered" in source

    def test_register_calls_append_log_record(self):
        source = (ROUTES_DIR / "auth.py").read_text(encoding="utf-8")
        # Find the register function and ensure it has append_log_record
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "register":
                func_source = ast.get_source_segment(source, node)
                assert "append_log_record" in func_source
                return
        pytest.fail("register function not found")


# ═════════════════════════════════════════════════════════════
# 9. Escalation resolve already has log record
# ═════════════════════════════════════════════════════════════


class TestEscalationResolveHasLog:
    """Confirm escalation resolve already writes a commitment record."""

    def test_resolve_escalation_has_append_log_record(self):
        source = (ROUTES_DIR / "admin.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "resolve_escalation":
                func_source = ast.get_source_segment(source, node)
                assert "append_log_record" in func_source
                return
        pytest.fail("resolve_escalation function not found")


# ═════════════════════════════════════════════════════════════
# 10. Commit guard module structure
# ═════════════════════════════════════════════════════════════


class TestCommitGuardModuleStructure:
    """Verify the commit_guard module exports the expected API."""

    def test_module_importable(self):
        mod = importlib.import_module("lumina.system_log.commit_guard")
        assert hasattr(mod, "requires_log_commit")
        assert hasattr(mod, "notify_log_commit")
        assert hasattr(mod, "LogCommitMissing")
        assert hasattr(mod, "is_commit_pending")
        assert hasattr(mod, "is_commit_satisfied")

    def test_audit_scanner_importable(self):
        mod = importlib.import_module("lumina.system_log.audit_scanner")
        assert hasattr(mod, "scan_source_ast")
        assert hasattr(mod, "scan_modules")
        assert hasattr(mod, "STATE_MUTATING_ENDPOINTS")
        assert hasattr(mod, "print_report")

    def test_log_commit_missing_is_runtime_error(self):
        assert issubclass(LogCommitMissing, RuntimeError)

    def test_state_mutating_registry_not_empty(self):
        from lumina.system_log.audit_scanner import STATE_MUTATING_ENDPOINTS
        assert len(STATE_MUTATING_ENDPOINTS) > 0
        total = sum(len(v) for v in STATE_MUTATING_ENDPOINTS.values())
        assert total >= 20, f"Expected >=20 registered endpoints, got {total}"
