"""Tests for Phase 4: System Log Integrity.

End-to-end verification of the System Log subsystem:
  1. JSONL ledger write + hash-chain verification
  2. Schema validation for all record types
  3. MANIFEST integrity (all hashes current)
  4. Commit guard infrastructure present on all adapters
  5. Version metadata present in all ledger schemas
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

# ─────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = REPO_ROOT / "ledger"
SRC_ROOT = REPO_ROOT / "src" / "lumina"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_trace_event(prev_hash: str = "genesis", **overrides: Any) -> dict:
    base = {
        "record_type": "TraceEvent",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_hash,
        "timestamp_utc": "2026-03-20T00:00:00Z",
        "session_id": "test-session-1",
        "actor_id": "test-actor",
        "event_type": "other",
        "decision": "test_decision",
    }
    base.update(overrides)
    return base


def _make_commitment_record(prev_hash: str = "genesis", **overrides: Any) -> dict:
    base = {
        "record_type": "CommitmentRecord",
        "record_id": str(uuid.uuid4()),
        "prev_record_hash": prev_hash,
        "timestamp_utc": "2026-03-20T00:00:00Z",
        "actor_id": "test-actor",
        "actor_role": "root",
        "commitment_type": "test_commit",
        "subject_id": "subject-1",
        "summary": "Test commitment record",
    }
    base.update(overrides)
    return base


# ═════════════════════════════════════════════════════════════
# 1. JSONL Ledger Write + Hash-Chain Verification
# ═════════════════════════════════════════════════════════════


class TestLedgerHashChain:
    """Verify that records can be hash-chained correctly."""

    def test_genesis_record(self):
        rec = _make_trace_event()
        assert rec["prev_record_hash"] == "genesis"

    def test_chain_two_records(self):
        r1 = _make_trace_event()
        r1_hash = _sha256(_canonical_json(r1))
        r2 = _make_trace_event(prev_hash=r1_hash)
        assert r2["prev_record_hash"] == r1_hash
        assert len(r2["prev_record_hash"]) == 64

    def test_chain_three_records(self):
        r1 = _make_trace_event()
        r1_hash = _sha256(_canonical_json(r1))
        r2 = _make_commitment_record(prev_hash=r1_hash)
        r2_hash = _sha256(_canonical_json(r2))
        r3 = _make_trace_event(prev_hash=r2_hash)
        assert r3["prev_record_hash"] == r2_hash

    def test_canonical_json_is_deterministic(self):
        rec = _make_trace_event()
        assert _canonical_json(rec) == _canonical_json(rec)
        # Keys should be sorted
        parsed = json.loads(_canonical_json(rec))
        assert list(parsed.keys()) == sorted(parsed.keys())

    def test_filesystem_adapter_writes_jsonl(self, tmp_path):
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter

        adapter = FilesystemPersistenceAdapter(tmp_path, tmp_path / "logs")
        rec = _make_trace_event()
        adapter.append_log_record("sess1", rec)

        ledger_path = adapter.get_log_ledger_path("sess1")
        lines = Path(ledger_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["record_type"] == "TraceEvent"

    def test_filesystem_chain_verification(self, tmp_path):
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter

        adapter = FilesystemPersistenceAdapter(tmp_path, tmp_path / "logs")

        r1 = _make_trace_event()
        adapter.append_log_record("sess1", r1)

        r1_hash = _sha256(_canonical_json(r1))
        r2 = _make_commitment_record(prev_hash=r1_hash)
        adapter.append_log_record("sess1", r2)

        result = adapter.validate_log_chain(session_id="sess1")
        assert result["intact"] is True
        assert result["records_checked"] == 2

    def test_broken_chain_detected(self, tmp_path):
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter

        adapter = FilesystemPersistenceAdapter(tmp_path, tmp_path / "logs")

        r1 = _make_trace_event()
        adapter.append_log_record("sess1", r1)

        # Intentionally wrong prev_record_hash
        r2 = _make_commitment_record(prev_hash="0" * 64)
        adapter.append_log_record("sess1", r2)

        result = adapter.validate_log_chain(session_id="sess1")
        assert result["intact"] is False


# ═════════════════════════════════════════════════════════════
# 2. Schema Validation for All Record Types
# ═════════════════════════════════════════════════════════════


_LEDGER_SCHEMAS = [
    "system-log-schema-v1.json",
    "trace-event-schema-v1.json",
    "commitment-record-schema-v1.json",
    "escalation-record-schema-v1.json",
    "ingestion-record-schema.json",
]


class TestLedgerSchemas:
    """Verify ledger schemas exist and have required structure."""

    @pytest.mark.parametrize("filename", _LEDGER_SCHEMAS)
    def test_schema_exists(self, filename):
        path = LEDGER_DIR / filename
        assert path.exists(), f"Ledger schema {filename} not found"

    @pytest.mark.parametrize("filename", _LEDGER_SCHEMAS)
    def test_schema_is_valid_json(self, filename):
        path = LEDGER_DIR / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @pytest.mark.parametrize("filename", _LEDGER_SCHEMAS)
    def test_schema_has_version(self, filename):
        path = LEDGER_DIR / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "schema_version" in data, f"{filename} missing schema_version"

    def test_prev_record_hash_pattern(self):
        """The system-log-schema should define the prev_record_hash pattern."""
        data = json.loads(
            (LEDGER_DIR / "system-log-schema-v1.json").read_text(encoding="utf-8")
        )
        schema_str = json.dumps(data)
        assert "prev_record_hash" in schema_str

    def test_trace_event_required_fields(self):
        data = json.loads(
            (LEDGER_DIR / "trace-event-schema-v1.json").read_text(encoding="utf-8")
        )
        required = set(data.get("required", []))
        expected = {"record_type", "record_id", "prev_record_hash", "timestamp_utc",
                    "session_id", "actor_id", "event_type", "decision"}
        assert expected <= required, f"Missing required fields: {expected - required}"

    def test_commitment_record_required_fields(self):
        data = json.loads(
            (LEDGER_DIR / "commitment-record-schema-v1.json").read_text(encoding="utf-8")
        )
        required = set(data.get("required", []))
        expected = {"record_type", "record_id", "prev_record_hash", "timestamp_utc",
                    "actor_id", "actor_role", "commitment_type", "subject_id", "summary"}
        assert expected <= required, f"Missing required fields: {expected - required}"


# ═════════════════════════════════════════════════════════════
# 3. MANIFEST Integrity
# ═════════════════════════════════════════════════════════════


class TestManifestIntegrity:
    """Verify MANIFEST.yaml hashes are current."""

    def test_manifest_check_passes(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "lumina.systools.manifest_integrity", "check"],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"Manifest check failed:\n{result.stdout}\n{result.stderr}"
        assert "PASS" in result.stdout

    def test_manifest_has_policy_doc(self):
        import yaml
        manifest = yaml.safe_load(
            (REPO_ROOT / "docs" / "MANIFEST.yaml").read_text(encoding="utf-8")
        )
        paths = {a["path"] for a in manifest.get("artifacts", [])}
        assert "docs/7-concepts/state-change-commit-policy.md" in paths


# ═════════════════════════════════════════════════════════════
# 4. Commit Guard Infrastructure
# ═════════════════════════════════════════════════════════════


class TestCommitGuardInfrastructure:
    """Verify the commit guard is wired into all persistence adapters."""

    def test_null_adapter_has_notify(self):
        import inspect
        from lumina.persistence.adapter import NullPersistenceAdapter
        source = inspect.getsource(NullPersistenceAdapter.append_log_record)
        assert "notify_log_commit" in source

    def test_filesystem_adapter_has_notify(self):
        import inspect
        from lumina.persistence.filesystem import FilesystemPersistenceAdapter
        source = inspect.getsource(FilesystemPersistenceAdapter.append_log_record)
        assert "notify_log_commit" in source

    def test_sqlite_adapter_has_notify(self):
        import inspect
        from lumina.persistence.sqlite import SQLitePersistenceAdapter
        source = inspect.getsource(SQLitePersistenceAdapter.append_log_record)
        assert "notify_log_commit" in source

    def test_audit_scanner_registry_complete(self):
        """audit_scanner registry covers at least 20 endpoints."""
        from lumina.system_log.audit_scanner import STATE_MUTATING_ENDPOINTS
        total = sum(len(v) for v in STATE_MUTATING_ENDPOINTS.values())
        assert total >= 20


# ═════════════════════════════════════════════════════════════
# 5. System Log Module Structure
# ═════════════════════════════════════════════════════════════


class TestSystemLogModuleStructure:
    """Verify the system_log package exposes the expected API."""

    def test_system_log_init(self):
        import lumina.system_log
        assert hasattr(lumina.system_log, "__path__")

    def test_commit_guard_importable(self):
        from lumina.system_log.commit_guard import (
            LogCommitMissing,
            is_commit_pending,
            is_commit_satisfied,
            notify_log_commit,
            requires_log_commit,
        )

    def test_audit_scanner_importable(self):
        from lumina.system_log.audit_scanner import (
            STATE_MUTATING_ENDPOINTS,
            print_report,
            scan_modules,
            scan_source_ast,
        )

    def test_admin_operations_importable(self):
        from lumina.system_log.admin_operations import (
            build_commitment_record,
            build_trace_event,
        )

    def test_cli_entry_point(self):
        """The system-log-validate CLI entry point is importable."""
        from lumina.cli.cli import system_log_validate
        assert callable(system_log_validate)


# ═════════════════════════════════════════════════════════════
# 6. Record Builders
# ═════════════════════════════════════════════════════════════


class TestRecordBuilders:
    """Verify record builders produce valid records."""

    def test_build_trace_event_structure(self):
        from lumina.system_log.admin_operations import build_trace_event
        rec = build_trace_event(
            session_id="s1", actor_id="a1", event_type="other",
            decision="test", evidence_summary={"key": "val"},
        )
        assert rec["record_type"] == "TraceEvent"
        assert rec["prev_record_hash"] == "genesis"
        assert "record_id" in rec
        assert "timestamp_utc" in rec

    def test_build_commitment_record_structure(self):
        from lumina.system_log.admin_operations import build_commitment_record
        rec = build_commitment_record(
            actor_id="a1", actor_role="root",
            commitment_type="test", subject_id="sub1",
            summary="Testing",
        )
        assert rec["record_type"] == "CommitmentRecord"
        assert rec["prev_record_hash"] == "genesis"
        assert "record_id" in rec
        assert "timestamp_utc" in rec
        assert rec["actor_role"] == "root"
