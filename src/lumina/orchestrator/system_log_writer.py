"""
system_log_writer.py — SystemLogWriter (the Scribe)

Owns all System Log I/O: hash-chaining, JSONL appending, and the three
canonical record types written by the PPA pipeline (CommitmentRecord,
TraceEvent, EscalationRecord) plus the auxiliary provenance TraceEvent.

Extracted from ppa_orchestrator.py so that the I/O concern is isolated
in one place.  The writer is synchronous today; the extraction makes it
trivial to swap in an async or queue-backed implementation later without
touching the orchestrator.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lumina.system_log.event_payload import LogLevel, create_event
from lumina.system_log import log_bus


# ─────────────────────────────────────────────────────────────
# Module-level hash utilities (mirrors ppa_orchestrator re-exports)
# ─────────────────────────────────────────────────────────────

def canonical_json(record: dict[str, Any]) -> bytes:
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def hash_record(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(record)).hexdigest()


def hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


# ─────────────────────────────────────────────────────────────
# SystemLogWriter
# ─────────────────────────────────────────────────────────────

class SystemLogWriter:
    """
    Owns all System Log persistence for a single session.

    Responsibilities:
    - Maintains the SHA-256 hash chain (``_prev_hash`` / ``_records``).
    - Writes CommitmentRecord, TraceEvent, and EscalationRecord to the
      JSONL ledger (directly or via the optional callback).
    - Exposes ``log_records`` for read-only replay by callers.

    The writer is intentionally free of domain decision logic: it takes
    fully-resolved values and writes them.
    """

    def __init__(
        self,
        ledger_path: str | Path,
        session_id: str,
        profile: dict[str, Any],
        *,
        system_physics_hash: str | None = None,
        log_append_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.session_id = session_id
        self._profile = profile
        self._system_physics_hash = system_physics_hash
        self._log_append_callback = log_append_callback
        self._prev_hash: str = "genesis"
        self._records: list[dict[str, Any]] = []

    # ── Public read-only view ─────────────────────────────────

    @property
    def log_records(self) -> list[dict[str, Any]]:
        """All System Log records written in this session (read-only copy)."""
        return list(self._records)

    # ── Low-level append (hash-chained) ──────────────────────

    def _append_log_record(self, record: dict[str, Any]) -> None:
        """Append one record to the JSONL ledger and advance the hash chain.

        When the log bus is running the record is also emitted as an
        AUDIT-level event so that the micro-router (and any other
        subscribers) can observe it.  The actual persistence still
        happens here — the bus is purely for fan-out notification.
        """
        if self._log_append_callback is not None:
            self._log_append_callback(self.session_id, record)
        else:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                )
                fh.write("\n")
        self._prev_hash = hash_record(record)
        self._records.append(record)

        # Emit AUDIT event to the log bus (no-op when bus is not running).
        log_bus.emit(create_event(
            source="system_log_writer",
            level=LogLevel.AUDIT,
            category="hash_chain",
            message=f"{record.get('record_type', 'record')} appended",
            record=record,
            domain_id=record.get("domain_pack_id"),
        ))

    # ── Record writers ────────────────────────────────────────

    def write_commitment_record(
        self,
        domain: dict[str, Any],
        policy_commitment: dict[str, Any],
    ) -> None:
        """Write the session-open CommitmentRecord to the System Logs."""
        domain_id = policy_commitment.get("subject_id", domain.get("id", "unknown"))
        domain_version = policy_commitment.get(
            "subject_version", domain.get("version", "unknown")
        )
        domain_hash = policy_commitment.get("subject_hash", "unknown")
        domain_authority = domain.get("domain_authority") or {}
        actor_id = domain_authority.get("pseudonymous_id", "unknown")
        record: dict[str, Any] = {
            "record_type": "CommitmentRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor_id,
            "actor_role": "domain_authority",
            "commitment_type": "domain_pack_activation",
            "subject_id": domain_id,
            "subject_version": domain_version,
            "subject_hash": domain_hash,
            "summary": (
                f"Session {self.session_id} opened — domain pack "
                f"{domain_id} v{domain_version} hash={str(domain_hash)[:12]}..."
            ),
            "references": [],
            "metadata": {"session_id": self.session_id},
        }
        self._append_log_record(record)

    def write_trace_event(
        self,
        task_spec: dict[str, Any],
        invariant_results: list[dict[str, Any]],
        domain_lib_decision: dict[str, Any],
        action: str | None,
        prompt_contract: dict[str, Any],
        provenance_metadata: dict[str, Any] | None,
        last_standing_order_id: str | None,
        last_standing_order_attempt: int | None,
    ) -> None:
        """Append a TraceEvent to the System Logs for this turn."""
        record: dict[str, Any] = {
            "record_type": "TraceEvent",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event_type": "turn_processed",
            "actor_id": self._profile.get(
                "subject_id", self._profile.get("student_id", "unknown")
            ),
            "actor_role": "subject",
            "decision": action,
            "decision_rationale": {
                "domain_lib_tier": domain_lib_decision.get("tier"),
                "domain_metric_pct": domain_lib_decision.get("drift_pct"),
                "domain_alert_flag": domain_lib_decision.get("frustration"),
                "standing_order_id": last_standing_order_id,
                "standing_order_attempt": last_standing_order_attempt,
                "invariant_failures": [
                    r["id"] for r in invariant_results if not r["passed"]
                ],
            },
            "task_id": task_spec.get("task_id", ""),
            "prompt_type": prompt_contract.get("prompt_type"),
            "metadata": dict(provenance_metadata or {}),
        }
        if self._system_physics_hash is not None:
            record["metadata"]["system_physics_hash"] = self._system_physics_hash
        for inv_result in invariant_results:
            if not inv_result["passed"] and inv_result.get("signal_type"):
                record["metadata"]["novel_synthesis_signal"] = inv_result["signal_type"]
                break
        self._append_log_record(record)

    def write_escalation_record(
        self,
        task_spec: dict[str, Any],
        domain_lib_decision: dict[str, Any],
        trigger: str,
        provenance_metadata: dict[str, Any] | None,
        domain_physics: dict[str, Any] | None = None,
    ) -> None:
        """Append an EscalationRecord to the System Logs."""
        # Resolve target_role and sla_minutes from domain physics
        # escalation_triggers when available, instead of hardcoding.
        target_role = "teacher"
        sla_minutes = 30
        if domain_physics:
            for et in domain_physics.get("escalation_triggers") or []:
                if et.get("id") == trigger:
                    target_role = et.get("target_role", target_role)
                    sla_minutes = et.get("sla_minutes", sla_minutes)
                    break

        record: dict[str, Any] = {
            "record_type": "EscalationRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "domain_pack_id": domain_physics.get("id", "") if domain_physics else "",
            "actor_id": self._profile.get(
                "subject_id", self._profile.get("student_id", "unknown")
            ),
            "actor_role": "subject",
            "status": "open",
            "trigger": trigger,
            "task_id": task_spec.get("task_id", ""),
            "domain_lib_decision": {
                "tier": domain_lib_decision.get("tier"),
                "domain_alert_flag": domain_lib_decision.get("frustration"),
                "domain_metric_pct": domain_lib_decision.get("drift_pct"),
            },
            "target_role": target_role,
            "escalation_target_id": self._profile.get("assigned_teacher_id") or None,
            "assigned_room_id": self._profile.get("assigned_room_id") or None,
            "sla_minutes": sla_minutes,
            "metadata": dict(provenance_metadata or {}),
        }
        if self._system_physics_hash is not None:
            record["metadata"]["system_physics_hash"] = self._system_physics_hash
        self._append_log_record(record)

        # ── Black-box capture on escalation trigger ───────────
        try:
            from lumina.session.blackbox_triggers import trigger_registry
            fired = trigger_registry.check(record)
            if fired:
                from lumina.session.blackbox import capture_blackbox, write_blackbox
                from lumina.api.session import _session_containers
                from lumina.daemon import resource_monitor as _rm

                container = _session_containers.get(self.session_id)
                rb_snap = container.ring_buffer.snapshot() if container and hasattr(container, "ring_buffer") else []
                telem = _rm.get_status().get("telemetry_window", {})
                sess_state = {
                    "task_id": task_spec.get("task_id", ""),
                    "turn_count": container.active_context.turn_count if container else 0,
                    "domain_id": container.active_domain_id if container else "",
                }
                recent_traces = [r for r in self.log_records[-10:] if r.get("record_type") == "TraceEvent"]

                snap = capture_blackbox(
                    session_id=self.session_id,
                    domain_id=sess_state.get("domain_id", ""),
                    trigger_type=",".join(fired),
                    trigger_source="escalation",
                    ring_buffer_snapshot=rb_snap,
                    telemetry_summary=telem,
                    recent_trace_events=recent_traces,
                    session_state=sess_state,
                )
                write_blackbox(snap)
        except Exception:
            import logging as _log_mod
            _log_mod.getLogger("lumina.blackbox").warning(
                "Black-box capture failed on escalation", exc_info=True,
            )

    def append_provenance_trace(
        self,
        task_id: str,
        action: str,
        prompt_type: str,
        metadata: dict[str, Any],
    ) -> None:
        """Append an auxiliary TraceEvent carrying post-payload provenance hashes."""
        record: dict[str, Any] = {
            "record_type": "TraceEvent",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": self._prev_hash,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event_type": "other",
            "actor_id": self._profile.get(
                "subject_id", self._profile.get("student_id", "unknown")
            ),
            "actor_role": "subject",
            "decision": action,
            "task_id": task_id,
            "prompt_type": prompt_type,
            "metadata": dict(metadata),
        }
        self._append_log_record(record)
