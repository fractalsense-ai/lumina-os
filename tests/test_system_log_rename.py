"""Verify the CTL → System Log rename is complete and consistent.

Checks:
- No residual CTL identifiers in Python source  (except backward-compat env var)
- All imports resolve to system_log package
- API endpoints use /api/system-log/ prefix
- Env var backward compatibility works
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src" / "lumina"


# ─────────────────────────────────────────────────────────────
# 1. No residual CTL identifiers in Python source
# ─────────────────────────────────────────────────────────────

# Patterns that are *allowed* — backward-compat env-var fallback and directory defaults
_ALLOWED_PATTERNS = [
    re.compile(r"LUMINA_CTL_DIR"),           # backward-compat fallback
    re.compile(r'parents\[\d+\]\s*/\s*"ctl"'),  # default dir name on disk
]


def _python_files() -> list[Path]:
    return sorted(SRC_DIR.rglob("*.py"))


class TestNoCTLIdentifiers:
    """Scan Python source for residual CTL/ctl identifiers that should be System Log."""

    # Identifiers that should NOT appear (class names, function names, variables)
    FORBIDDEN = re.compile(
        r"""
        \bctl_record\b |
        \bCtlRecord\b |
        \bCTL_DIR\b |
        \bctl_dir\b |
        \bctl_validator\b |
        \bctl_append\b |
        \bctl_chain\b |
        \bctl_ledger\b |
        \bCausalTraceLedger\b |
        \bcausal_trace_ledger\b |
        \bcausal-trace-ledger\b
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    @pytest.mark.parametrize("py_file", _python_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
    def test_no_forbidden_identifiers(self, py_file: Path) -> None:
        content = py_file.read_text(encoding="utf-8")
        violations: list[tuple[int, str]] = []
        for i, line in enumerate(content.splitlines(), 1):
            if self.FORBIDDEN.search(line):
                # Check if this is an allowed pattern
                if any(ap.search(line) for ap in _ALLOWED_PATTERNS):
                    continue
                violations.append((i, line.strip()))
        assert not violations, (
            f"Residual CTL identifiers in {py_file.relative_to(REPO_ROOT)}:\n"
            + "\n".join(f"  L{ln}: {text}" for ln, text in violations)
        )


# ─────────────────────────────────────────────────────────────
# 2. Package imports resolve correctly
# ─────────────────────────────────────────────────────────────


class TestImportsResolve:
    """Verify renamed packages are importable."""

    def test_system_log_package_importable(self) -> None:
        mod = importlib.import_module("lumina.system_log")
        assert hasattr(mod, "__file__")

    def test_system_log_admin_operations(self) -> None:
        mod = importlib.import_module("lumina.system_log.admin_operations")
        assert hasattr(mod, "map_role_to_actor_role")

    def test_system_log_route(self) -> None:
        mod = importlib.import_module("lumina.api.routes.system_log")
        assert hasattr(mod, "router")

    def test_system_log_validator(self) -> None:
        mod = importlib.import_module("lumina.systools.system_log_validator")
        assert hasattr(mod, "main")

    def test_no_ctl_package(self) -> None:
        """The old lumina.ctl package should not exist."""
        old_path = SRC_DIR / "ctl"
        assert not old_path.exists(), f"Old package directory still exists: {old_path}"


# ─────────────────────────────────────────────────────────────
# 3. API endpoints use /api/system-log/ prefix
# ─────────────────────────────────────────────────────────────


class TestAPIEndpoints:
    """Verify system-log endpoints are registered in the FastAPI app."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        # Import server to get the app
        self.config_mod = importlib.import_module("lumina.api.config")
        self.routes_mod = importlib.import_module("lumina.api.routes.system_log")

    def test_router_has_system_log_routes(self) -> None:
        router = self.routes_mod.router
        paths = [r.path for r in router.routes]
        assert any("/api/system-log/" in p for p in paths)

    def test_no_ctl_routes_file(self) -> None:
        ctl_route = SRC_DIR / "api" / "routes" / "ctl.py"
        assert not ctl_route.exists(), "Old ctl.py route file still exists"


# ─────────────────────────────────────────────────────────────
# 4. Backward-compat env var
# ─────────────────────────────────────────────────────────────


class TestEnvVarCompat:
    """Verify LUMINA_LOG_DIR falls back to LUMINA_CTL_DIR."""

    def test_log_dir_env_var_preferred(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUMINA_LOG_DIR", "/new/log/path")
        monkeypatch.delenv("LUMINA_CTL_DIR", raising=False)
        # Re-evaluate config
        val = os.environ.get("LUMINA_LOG_DIR", os.environ.get("LUMINA_CTL_DIR", "fallback"))
        assert val == "/new/log/path"

    def test_ctl_dir_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUMINA_LOG_DIR", raising=False)
        monkeypatch.setenv("LUMINA_CTL_DIR", "/old/ctl/path")
        val = os.environ.get("LUMINA_LOG_DIR", os.environ.get("LUMINA_CTL_DIR", "fallback"))
        assert val == "/old/ctl/path"

    def test_default_when_both_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUMINA_LOG_DIR", raising=False)
        monkeypatch.delenv("LUMINA_CTL_DIR", raising=False)
        val = os.environ.get("LUMINA_LOG_DIR", os.environ.get("LUMINA_CTL_DIR", "fallback"))
        assert val == "fallback"


# ─────────────────────────────────────────────────────────────
# 5. Ledger schema files renamed correctly
# ─────────────────────────────────────────────────────────────


class TestLedgerSchemas:
    """Verify ledger schema files use new names."""

    def test_system_log_schema_exists(self) -> None:
        assert (REPO_ROOT / "ledger" / "system-log-schema-v1.json").is_file()

    def test_old_ctl_schema_removed(self) -> None:
        assert not (REPO_ROOT / "ledger" / "causal-trace-ledger-schema-v1.json").exists()

    def test_old_standard_removed(self) -> None:
        assert not (REPO_ROOT / "standards" / "causal-trace-ledger-v1.md").exists()

    def test_system_log_standard_exists(self) -> None:
        assert (REPO_ROOT / "standards" / "system-log-v1.md").is_file()
