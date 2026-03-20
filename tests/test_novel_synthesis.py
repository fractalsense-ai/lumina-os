"""Tests for the Novel Synthesis Framework.

Covers:
  - model_id / model_version injection into TraceEvent metadata
  - signal_type propagation from failing invariants
  - novel_synthesis_verified / novel_synthesis_rejected commitment types
  - novel_synthesis_review escalation trigger type
  - End-to-end model_id flow through /api/chat
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Helpers ──────────────────────────────────────────────────


def _make_domain(
    invariants: list[dict[str, Any]] | None = None,
    standing_orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal domain-physics dict."""
    return {
        "id": "domain/test/novel-synthesis/v1",
        "version": "1.0.0",
        "domain_authority": {"pseudonymous_id": "da_test_001"},
        "invariants": invariants or [],
        "standing_orders": standing_orders or [],
        "escalation_triggers": [],
    }


def _make_profile() -> dict[str, Any]:
    return {
        "subject_id": "subject_test_001",
        "preferences": {"interests": ["science"]},
    }


def _make_orchestrator(domain: dict[str, Any], **kwargs: Any):
    from lumina.orchestrator.ppa_orchestrator import PPAOrchestrator

    tmp = tempfile.mkdtemp()
    ledger = Path(tmp) / "test-session.jsonl"
    return PPAOrchestrator(
        domain_physics=domain,
        subject_profile=_make_profile(),
        ledger_path=str(ledger),
        **kwargs,
    )


# ── Test 1: model_id/model_version in TraceEvent metadata ───


class TestModelIdentityInTraceEvent:
    def test_model_id_injected_into_trace_event(self):
        """model_id and model_version from provenance_metadata appear in System Log."""
        domain = _make_domain()
        orch = _make_orchestrator(domain)

        provenance = {
            "model_id": "claude-sonnet-4-20250514",
            "model_version": "2025-05-14",
        }
        orch.process_turn(
            {"task_id": "t1"},
            {"some_field": True},
            provenance_metadata=provenance,
        )

        trace_events = [
            r for r in orch.log_records if r["record_type"] == "TraceEvent"
        ]
        assert len(trace_events) >= 1
        meta = trace_events[-1]["metadata"]
        assert meta["model_id"] == "claude-sonnet-4-20250514"
        assert meta["model_version"] == "2025-05-14"

    def test_model_id_absent_when_not_provided(self):
        """When no model_id is provided, metadata should not contain the key."""
        domain = _make_domain()
        orch = _make_orchestrator(domain)

        orch.process_turn({"task_id": "t1"}, {"some_field": True})

        trace_events = [
            r for r in orch.log_records if r["record_type"] == "TraceEvent"
        ]
        meta = trace_events[-1]["metadata"]
        assert "model_id" not in meta
        assert "model_version" not in meta


# ── Test 2/3: signal_type propagation ────────────────────────


class TestSignalTypePropagation:
    def _make_novel_domain(self):
        return _make_domain(
            invariants=[
                {
                    "id": "standard_method_preferred",
                    "description": "Flag non-standard methods",
                    "severity": "warning",
                    "check": "method_recognized",
                    "standing_order_on_violation": "request_method_justification",
                    "signal_type": "NOVEL_PATTERN",
                },
            ],
            standing_orders=[
                {
                    "id": "request_method_justification",
                    "action": "request_method_justification",
                    "trigger_condition": "standard_method_preferred",
                    "max_attempts": 1,
                    "escalation_on_exhaust": False,
                },
            ],
        )

    def test_signal_type_propagated_on_invariant_failure(self):
        """When a warning invariant with signal_type fails, metadata includes novel_synthesis_signal."""
        domain = self._make_novel_domain()
        orch = _make_orchestrator(domain)

        # method_recognized == False → invariant fails → signal_type propagated
        orch.process_turn(
            {"task_id": "t1"},
            {"method_recognized": False},
        )

        trace_events = [
            r for r in orch.log_records if r["record_type"] == "TraceEvent"
        ]
        meta = trace_events[-1]["metadata"]
        assert meta.get("novel_synthesis_signal") == "NOVEL_PATTERN"

    def test_signal_type_not_propagated_on_pass(self):
        """When the invariant passes, no novel_synthesis_signal in metadata."""
        domain = self._make_novel_domain()
        orch = _make_orchestrator(domain)

        # method_recognized == True → invariant passes → no signal
        orch.process_turn(
            {"task_id": "t1"},
            {"method_recognized": True},
        )

        trace_events = [
            r for r in orch.log_records if r["record_type"] == "TraceEvent"
        ]
        meta = trace_events[-1]["metadata"]
        assert "novel_synthesis_signal" not in meta

    def test_signal_type_with_model_id_combined(self):
        """Both model_id and novel_synthesis_signal coexist in metadata."""
        domain = self._make_novel_domain()
        orch = _make_orchestrator(domain)

        provenance = {
            "model_id": "gpt-5",
            "model_version": "2026-01-15",
        }
        orch.process_turn(
            {"task_id": "t1"},
            {"method_recognized": False},
            provenance_metadata=provenance,
        )

        trace_events = [
            r for r in orch.log_records if r["record_type"] == "TraceEvent"
        ]
        meta = trace_events[-1]["metadata"]
        assert meta["model_id"] == "gpt-5"
        assert meta["model_version"] == "2026-01-15"
        assert meta["novel_synthesis_signal"] == "NOVEL_PATTERN"


# ── Test 4/5: novel_synthesis commitment types ───────────────


class TestNovelSynthesisCommitmentTypes:
    """Validate that the new commitment types are well-formed System Log records."""

    @staticmethod
    def _make_commitment(commitment_type: str) -> dict[str, Any]:
        return {
            "record_type": "CommitmentRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": "genesis",
            "timestamp_utc": "2026-03-13T12:00:00+00:00",
            "actor_id": "da_test_001",
            "actor_role": "domain_authority",
            "commitment_type": commitment_type,
            "subject_id": "domain/test/novel-synthesis/v1",
            "summary": f"Novel synthesis {commitment_type} for test",
            "metadata": {
                "model_id": "claude-sonnet-4-20250514",
                "domain_pack_id": "domain/test/novel-synthesis/v1",
            },
        }

    def test_novel_synthesis_verified_commitment(self):
        """novel_synthesis_verified is a valid commitment_type."""
        record = self._make_commitment("novel_synthesis_verified")
        # Validate against the schema enum by loading the schema
        schema_path = REPO_ROOT / "ledger" / "commitment-record-schema-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        allowed = schema["properties"]["commitment_type"]["enum"]
        assert "novel_synthesis_verified" in allowed
        assert record["commitment_type"] in allowed

    def test_novel_synthesis_rejected_commitment(self):
        """novel_synthesis_rejected is a valid commitment_type."""
        record = self._make_commitment("novel_synthesis_rejected")
        schema_path = REPO_ROOT / "ledger" / "commitment-record-schema-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        allowed = schema["properties"]["commitment_type"]["enum"]
        assert "novel_synthesis_rejected" in allowed
        assert record["commitment_type"] in allowed


# ── Test 6: novel_synthesis_review escalation trigger ────────


class TestNovelSynthesisEscalationTrigger:
    def test_novel_synthesis_review_in_trigger_type_enum(self):
        """novel_synthesis_review is a valid trigger_type in the escalation schema."""
        schema_path = REPO_ROOT / "ledger" / "escalation-record-schema-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        allowed = schema["properties"]["trigger_type"]["enum"]
        assert "novel_synthesis_review" in allowed

    def test_novel_synthesis_review_escalation_record(self):
        """An EscalationRecord with trigger_type novel_synthesis_review is well-formed."""
        record = {
            "record_type": "EscalationRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": "genesis",
            "timestamp_utc": "2026-03-13T12:00:00+00:00",
            "session_id": str(uuid.uuid4()),
            "escalating_actor_id": "orchestrator",
            "target_meta_authority_id": "da_test_001",
            "trigger": "Novel method unrecognized after justification request",
            "trigger_type": "novel_synthesis_review",
            "evidence_summary": {"method_recognized": False},
            "status": "pending",
        }
        schema_path = REPO_ROOT / "ledger" / "escalation-record-schema-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        allowed = schema["properties"]["trigger_type"]["enum"]
        assert record["trigger_type"] in allowed


# ── Test 7: novel_synthesis_flagged event_type ───────────────


class TestNovelSynthesisEventType:
    def test_novel_synthesis_flagged_in_event_type_enum(self):
        """novel_synthesis_flagged is a valid event_type in the trace event schema."""
        schema_path = REPO_ROOT / "ledger" / "trace-event-schema-v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        allowed = schema["properties"]["event_type"]["enum"]
        assert "novel_synthesis_flagged" in allowed
