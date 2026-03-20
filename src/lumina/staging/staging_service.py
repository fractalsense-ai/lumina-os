"""Staging Service — orchestrates the stage → review → approve/reject lifecycle.

All LLM-generated file payloads pass through this service.  The workflow:

1. ``stage_file()`` — validates via ``InspectionPipeline``, writes a JSON
   envelope to ``data/staging/{staged_id}.json``.
2. ``list_staged()`` — returns pending envelopes for DA/QA review.
3. ``approve_staged()`` — calls ``write_from_template`` to the final path,
   writes a System Log commitment record.
4. ``reject_staged()`` — marks the envelope rejected, writes a System Log record.

The staging directory defaults to ``data/staging/`` relative to the
repository root but can be overridden at construction time.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lumina.system_log.admin_operations import (
    build_commitment_record,
    map_role_to_actor_role,
)
from lumina.staging.file_writer import write_from_template
from lumina.staging.template_registry import TemplateRegistry

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------

@dataclass
class StagedFile:
    """Envelope stored as JSON in the staging directory."""

    staged_id: str
    template_id: str
    actor_id: str
    actor_role: str
    payload: dict[str, Any]
    staged_at: str
    approval_status: str = "pending"       # pending | approved | rejected
    approver_id: str | None = None
    resolved_at: str | None = None
    final_path: str | None = None
    log_record_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------
# Service
# ------------------------------------------------------------------

_DEFAULT_STAGING_DIR = Path(__file__).resolve().parents[3] / "data" / "staging"


class StagingService:
    """Manages the staged-file lifecycle on disk.

    Parameters
    ----------
    staging_dir:
        Directory where JSON envelopes are persisted.  Defaults to
        ``<repo>/data/staging/``.
    repo_root:
        Repository root used to resolve template target patterns.
    """

    def __init__(
        self,
        staging_dir: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._staging_dir = (staging_dir or _DEFAULT_STAGING_DIR).resolve()
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        self._lock = threading.Lock()

    # -- Stage --------------------------------------------------------

    def stage_file(
        self,
        payload: dict[str, Any],
        template_id: str,
        actor_id: str,
        actor_role: str = "domain_authority",
    ) -> StagedFile:
        """Validate and stage a file for review.

        Raises
        ------
        ValueError — unknown template or missing required fields.
        """
        template = TemplateRegistry.require(template_id)

        # Check required fields before persisting
        missing = [f for f in template.required_fields if f not in payload]
        if missing:
            raise ValueError(
                f"Payload missing required fields for template "
                f"{template_id!r}: {missing}"
            )

        staged_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        envelope = StagedFile(
            staged_id=staged_id,
            template_id=template_id,
            actor_id=actor_id,
            actor_role=actor_role,
            payload=payload,
            staged_at=now,
        )

        # Write System Log record for staging
        log_rec = build_commitment_record(
            actor_id=actor_id,
            actor_role=map_role_to_actor_role(actor_role),
            commitment_type="hitl_command_staged",
            subject_id=staged_id,
            summary=f"File staged: template={template_id}",
            metadata={"template_id": template_id},
        )
        envelope.log_record_id = log_rec.get("record_id")

        # Persist envelope
        with self._lock:
            path = self._staging_dir / f"{staged_id}.json"
            path.write_text(
                json.dumps(envelope.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        log.info("Staged file %s (template=%s, actor=%s)", staged_id, template_id, actor_id)
        return envelope

    # -- List ---------------------------------------------------------

    def list_staged(self, actor_id: str | None = None) -> list[StagedFile]:
        """Return all staged file envelopes, optionally filtered by *actor_id*."""
        results: list[StagedFile] = []
        with self._lock:
            for path in sorted(self._staging_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if "staged_id" not in data:
                    continue
                if actor_id and data.get("actor_id") != actor_id:
                    continue
                results.append(StagedFile(**{
                    k: v for k, v in data.items() if k in StagedFile.__dataclass_fields__
                }))
        return results

    def get_staged(self, staged_id: str) -> StagedFile | None:
        """Load a single staged envelope by ID."""
        path = self._staging_dir / f"{staged_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return StagedFile(**{
            k: v for k, v in data.items() if k in StagedFile.__dataclass_fields__
        })

    # -- Approve ------------------------------------------------------

    def approve_staged(
        self,
        staged_id: str,
        approver_id: str,
        approver_role: str = "domain_authority",
        target_overrides: dict[str, str] | None = None,
    ) -> Path:
        """Approve a staged file — write to final destination.

        Parameters
        ----------
        target_overrides:
            Dict of placeholder substitutions for the template's
            ``target_pattern`` (e.g. ``{"domain_short": "education"}``).

        Returns
        -------
        Path to the written file.

        Raises
        ------
        ValueError — staged file not found or already resolved.
        """
        envelope = self._load_and_check(staged_id)

        template = TemplateRegistry.require(envelope.template_id)

        # Resolve target path
        subs = dict(target_overrides or {})
        # Try to derive common substitutions from the payload
        payload = envelope.payload
        subs.setdefault("domain_short", _extract_domain_short(payload))
        subs.setdefault("name", payload.get("profile_id", payload.get("id", staged_id)))
        target_rel = template.target_pattern.format_map(_SafeFormatMap(subs))
        target_path = self._repo_root / target_rel

        # Write via deterministic actuator
        final = write_from_template(
            template_id=envelope.template_id,
            validated_payload=payload,
            target_path=target_path,
        )

        # System Log record
        log_rec = build_commitment_record(
            actor_id=approver_id,
            actor_role=map_role_to_actor_role(approver_role),
            commitment_type="hitl_command_accepted",
            subject_id=staged_id,
            summary=f"Approved staged file → {target_rel}",
            metadata={"template_id": envelope.template_id, "final_path": str(final)},
        )

        # Update envelope
        envelope.approval_status = "approved"
        envelope.approver_id = approver_id
        envelope.resolved_at = datetime.now(timezone.utc).isoformat()
        envelope.final_path = str(final)
        envelope.log_record_id = log_rec.get("record_id")
        self._persist_envelope(envelope)

        log.info("Approved staged file %s → %s", staged_id, final)
        return final

    # -- Reject -------------------------------------------------------

    def reject_staged(
        self,
        staged_id: str,
        approver_id: str,
        approver_role: str = "domain_authority",
        reason: str = "",
    ) -> None:
        """Reject a staged file — mark as rejected, write System Log record."""
        envelope = self._load_and_check(staged_id)

        log_rec = build_commitment_record(
            actor_id=approver_id,
            actor_role=map_role_to_actor_role(approver_role),
            commitment_type="hitl_command_rejected",
            subject_id=staged_id,
            summary=f"Rejected staged file: {reason or 'no reason given'}",
            metadata={"template_id": envelope.template_id, "reason": reason},
        )

        envelope.approval_status = "rejected"
        envelope.approver_id = approver_id
        envelope.resolved_at = datetime.now(timezone.utc).isoformat()
        envelope.log_record_id = log_rec.get("record_id")
        self._persist_envelope(envelope)

        log.info("Rejected staged file %s (reason=%s)", staged_id, reason)

    # -- Internals ----------------------------------------------------

    def _load_and_check(self, staged_id: str) -> StagedFile:
        envelope = self.get_staged(staged_id)
        if envelope is None:
            raise ValueError(f"Staged file not found: {staged_id!r}")
        if envelope.approval_status != "pending":
            raise ValueError(
                f"Staged file {staged_id!r} already resolved "
                f"({envelope.approval_status})"
            )
        return envelope

    def _persist_envelope(self, envelope: StagedFile) -> None:
        with self._lock:
            path = self._staging_dir / f"{envelope.staged_id}.json"
            path.write_text(
                json.dumps(envelope.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_domain_short(payload: dict[str, Any]) -> str:
    """Best-effort extraction of a domain short name from the payload."""
    for key in ("domain_id", "domain_short"):
        val = payload.get(key, "")
        if isinstance(val, str) and val:
            # domain/edu/algebra-level-1/v1 → edu
            parts = val.split("/")
            if len(parts) >= 2:
                return parts[1]
            return val
    return "unknown"


class _SafeFormatMap(dict):  # type: ignore[type-arg]
    """dict subclass that returns the placeholder unchanged on missing keys."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
