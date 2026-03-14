"""
service.py — Document Ingestion Service

Orchestrates the full ingestion lifecycle:
  upload -> extract -> interpret (SLM) -> review (DA) -> commit (CTL)

RBAC: ``ingest`` permission required to upload.  Domain authority
on the governed module required to review and commit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Callable

from lumina.ingestion.extractors import extract_text, extract_structured
from lumina.ingestion.interpreter import generate_interpretations

log = logging.getLogger("lumina-ingestion")


class IngestService:
    """Stateful document ingestion manager.

    Stores ingestion records in-memory (keyed by ingestion_id) and
    delegates persistence to the supplied append/query callbacks.
    Production deployments should back this with the persistence adapter.
    """

    def __init__(
        self,
        *,
        persistence_append: Callable[..., None] | None = None,
        persistence_query: Callable[..., list[dict[str, Any]]] | None = None,
        call_slm_fn: Callable[..., str] | None = None,
        max_file_size_mb: int = 10,
    ) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._raw_docs: dict[str, bytes] = {}
        self._persistence_append = persistence_append
        self._persistence_query = persistence_query
        self._call_slm_fn = call_slm_fn
        self._max_file_size_mb = max_file_size_mb

    # ── Upload ────────────────────────────────────────────────

    def accept_document(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        actor_id: str,
        domain_id: str,
        module_id: str | None = None,
    ) -> str:
        """Accept an uploaded document and create an IngestionRecord.

        Returns the ingestion_id (also the document_id).
        Raises ``ValueError`` for invalid content type or size violations.
        """
        size_mb = len(file_bytes) / (1024 * 1024)
        if size_mb > self._max_file_size_mb:
            raise ValueError(
                f"File size {size_mb:.1f}MB exceeds limit of {self._max_file_size_mb}MB"
            )

        valid_types = {"pdf", "docx", "markdown", "csv", "json", "yaml"}
        if content_type not in valid_types:
            raise ValueError(f"Unsupported content type: {content_type!r}")

        doc_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(file_bytes).hexdigest()

        record: dict[str, Any] = {
            "record_type": "IngestionRecord",
            "record_id": str(uuid.uuid4()),
            "prev_record_hash": "genesis",
            "timestamp_utc": _utc_now_iso(),
            "document_id": doc_id,
            "original_filename": filename,
            "content_hash": content_hash,
            "content_type": content_type,
            "ingesting_actor_id": actor_id,
            "domain_id": domain_id,
            "module_id": module_id,
            "status": "pending_extraction",
            "interpretations": [],
            "selected_interpretation_id": None,
            "review_decision": None,
            "reviewer_id": None,
            "review_notes": None,
            "committed_hash": None,
        }

        self._records[doc_id] = record
        self._raw_docs[doc_id] = file_bytes

        log.info(
            "Ingestion accepted: doc=%s file=%s domain=%s actor=%s",
            doc_id, filename, domain_id, actor_id,
        )
        return doc_id

    # ── Extract & Interpret ───────────────────────────────────

    def extract_interpretations(
        self,
        ingestion_id: str,
        domain_physics: dict[str, Any],
        glossary: list[dict[str, Any]] | None = None,
        module_context: dict[str, Any] | None = None,
        max_interpretations: int = 3,
    ) -> list[dict[str, Any]]:
        """Run SLM extraction and generate interpretation variants.

        Updates the IngestionRecord status and stores interpretations.
        Returns the list of interpretation dicts.
        """
        record = self._get_record(ingestion_id)
        raw = self._raw_docs.get(ingestion_id)
        if raw is None:
            raise ValueError(f"Raw document not found for {ingestion_id}")

        record["status"] = "extracting"
        content_type = record.get("content_type", "markdown")

        # Extract text from document
        extracted = extract_text(raw, content_type)

        # Generate interpretations via SLM
        interpretations = generate_interpretations(
            extracted_text=extracted,
            domain_physics=domain_physics,
            glossary=glossary,
            module_context=module_context,
            max_interpretations=max_interpretations,
            call_slm_fn=self._call_slm_fn,
        )

        record["interpretations"] = interpretations
        record["status"] = "extraction_complete"
        log.info(
            "Extraction complete: doc=%s variants=%d",
            ingestion_id, len(interpretations),
        )
        return interpretations

    # ── Review ────────────────────────────────────────────────

    def review_interpretation(
        self,
        ingestion_id: str,
        decision: str,
        reviewer_id: str,
        selected_interpretation_id: str | None = None,
        edits: dict[str, Any] | None = None,
        review_notes: str | None = None,
    ) -> dict[str, Any]:
        """Submit a review decision for an ingestion.

        Parameters
        ----------
        decision:
            One of ``approve``, ``reject``, ``edit``.
        selected_interpretation_id:
            Required for ``approve``; identifies which interpretation.
        edits:
            For ``edit`` decisions, a dict with updated yaml_content.
        review_notes:
            Optional reviewer notes (max 512 chars).

        Returns the updated IngestionRecord.
        """
        record = self._get_record(ingestion_id)

        if decision not in ("approve", "reject", "edit"):
            raise ValueError(f"Invalid decision: {decision!r}")

        if decision == "approve" and not selected_interpretation_id:
            raise ValueError("selected_interpretation_id required for approve")

        if decision == "approve":
            # Validate selected interpretation exists
            interp_ids = [i["id"] for i in record.get("interpretations", [])]
            if selected_interpretation_id not in interp_ids:
                raise ValueError(f"Interpretation {selected_interpretation_id!r} not found")

        if decision == "edit" and edits:
            # Apply edits to the selected interpretation or create new one
            new_interp = {
                "id": str(uuid.uuid4()),
                "label": "edited",
                "yaml_content": edits.get("yaml_content", ""),
                "confidence": 1.0,
                "ambiguity_notes": "Manually edited by domain authority.",
            }
            record["interpretations"].append(new_interp)
            selected_interpretation_id = new_interp["id"]

        record["review_decision"] = decision
        record["reviewer_id"] = reviewer_id
        record["selected_interpretation_id"] = selected_interpretation_id
        record["review_notes"] = (review_notes or "")[:512]

        if decision == "reject":
            record["status"] = "rejected"
        else:
            record["status"] = "approved"

        log.info(
            "Review submitted: doc=%s decision=%s reviewer=%s",
            ingestion_id, decision, reviewer_id,
        )
        return record

    # ── Commit ────────────────────────────────────────────────

    def commit_ingestion(
        self,
        ingestion_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        """Finalize an approved ingestion: convert YAML to JSON, hash, CTL commit.

        Returns a dict with ``committed_hash`` and ``record_id``.
        """
        record = self._get_record(ingestion_id)

        if record["status"] != "approved":
            raise ValueError(
                f"Cannot commit ingestion in status {record['status']!r}; must be 'approved'"
            )

        sel_id = record.get("selected_interpretation_id")
        if not sel_id:
            raise ValueError("No interpretation selected")

        # Find selected interpretation
        selected = None
        for interp in record.get("interpretations", []):
            if interp["id"] == sel_id:
                selected = interp
                break
        if selected is None:
            raise ValueError(f"Selected interpretation {sel_id!r} not found")

        # Convert YAML content to JSON
        yaml_text = selected["yaml_content"]
        try:
            from lumina.core.yaml_loader import load_yaml_string
            parsed = load_yaml_string(yaml_text)
        except Exception:
            # Fallback: treat as raw text artifact
            parsed = {"raw_content": yaml_text}

        json_bytes = json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        committed_hash = hashlib.sha256(json_bytes).hexdigest()

        record["committed_hash"] = committed_hash
        record["status"] = "committed"

        # Write CTL commitment record if persistence is wired
        if self._persistence_append:
            from lumina.ctl.admin_operations import build_commitment_record
            commitment = build_commitment_record(
                actor_id=actor_id,
                actor_role="domain_authority",
                commitment_type="ingestion_committed",
                subject_id=ingestion_id,
                summary=f"Ingestion committed: {record['original_filename']}",
                subject_hash=committed_hash,
                metadata={
                    "document_id": record["document_id"],
                    "domain_id": record["domain_id"],
                    "module_id": record.get("module_id"),
                    "content_type": record.get("content_type"),
                    "interpretation_label": selected.get("label"),
                },
            )
            try:
                self._persistence_append("admin", commitment)
            except Exception as exc:
                log.warning("Failed to write ingestion CTL record: %s", exc)

        log.info(
            "Ingestion committed: doc=%s hash=%s",
            ingestion_id, committed_hash,
        )
        return {
            "committed_hash": committed_hash,
            "record_id": record["record_id"],
            "document_id": record["document_id"],
            "status": "committed",
        }

    # ── Query ─────────────────────────────────────────────────

    def get_record(self, ingestion_id: str) -> dict[str, Any] | None:
        """Return an IngestionRecord or None."""
        return self._records.get(ingestion_id)

    def list_records(
        self,
        domain_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List ingestion records with optional filters."""
        records = list(self._records.values())
        if domain_id:
            records = [r for r in records if r.get("domain_id") == domain_id]
        if status:
            records = [r for r in records if r.get("status") == status]
        records.sort(key=lambda r: r.get("timestamp_utc", ""), reverse=True)
        return records[offset: offset + limit]

    # ── Internal ──────────────────────────────────────────────

    def _get_record(self, ingestion_id: str) -> dict[str, Any]:
        record = self._records.get(ingestion_id)
        if record is None:
            raise ValueError(f"Ingestion record not found: {ingestion_id!r}")
        return record


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
