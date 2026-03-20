"""Tests for the document ingestion pipeline.

Covers: extractors, interpreter (with mock SLM), IngestService lifecycle,
RBAC gating, multi-interpretation review, and System Log commitment.
"""

from __future__ import annotations

import json
import uuid

import pytest


# ── Extractor tests ──────────────────────────────────────────

class TestExtractors:
    """Tests for lumina.ingestion.extractors."""

    def test_extract_markdown(self):
        from lumina.ingestion.extractors import extract_text
        raw = b"# Title\n\nSome paragraph."
        assert extract_text(raw, "markdown") == "# Title\n\nSome paragraph."

    def test_extract_csv(self):
        from lumina.ingestion.extractors import extract_text
        raw = b"a,b,c\n1,2,3\n"
        result = extract_text(raw, "csv")
        assert "a | b | c" in result
        assert "1 | 2 | 3" in result

    def test_extract_json(self):
        from lumina.ingestion.extractors import extract_text
        raw = json.dumps({"key": "value"}).encode()
        result = extract_text(raw, "json")
        assert '"key"' in result
        assert '"value"' in result

    def test_extract_yaml(self):
        from lumina.ingestion.extractors import extract_text
        raw = b"key: value\nlist:\n  - one\n"
        result = extract_text(raw, "yaml")
        assert "key: value" in result

    def test_extract_unsupported_raises(self):
        from lumina.ingestion.extractors import extract_text
        with pytest.raises(ValueError, match="Unsupported content type"):
            extract_text(b"data", "binary")

    def test_extract_structured_json(self):
        from lumina.ingestion.extractors import extract_structured
        raw = json.dumps({"a": 1}).encode()
        assert extract_structured(raw, "json") == {"a": 1}

    def test_extract_structured_unsupported(self):
        from lumina.ingestion.extractors import extract_structured
        with pytest.raises(ValueError, match="only supports json/yaml"):
            extract_structured(b"hi", "csv")


# ── Interpreter tests ───────────────────────────────────────

class TestInterpreter:
    """Tests for lumina.ingestion.interpreter (with mock SLM)."""

    @staticmethod
    def _mock_slm_single(**_kw):
        return json.dumps({
            "interpretations": [{
                "label": "default",
                "yaml_content": "module_id: test-mod\nartifacts: []",
                "confidence": 0.95,
                "ambiguity_notes": "Unambiguous mapping.",
            }]
        })

    @staticmethod
    def _mock_slm_multi(**_kw):
        return json.dumps({
            "interpretations": [
                {"label": "strict", "yaml_content": "strict: true", "confidence": 0.8, "ambiguity_notes": ""},
                {"label": "loose", "yaml_content": "loose: true", "confidence": 0.6, "ambiguity_notes": ""},
                {"label": "hierarchical", "yaml_content": "hier: true", "confidence": 0.5, "ambiguity_notes": ""},
            ]
        })

    def test_single_interpretation(self):
        from lumina.ingestion.interpreter import generate_interpretations
        result = generate_interpretations(
            extracted_text="hello world",
            domain_physics={"id": "test", "description": "test domain"},
            call_slm_fn=self._mock_slm_single,
        )
        assert len(result) == 1
        assert result[0]["label"] == "default"
        assert result[0]["confidence"] == 0.95
        assert "id" in result[0]

    def test_multi_interpretation(self):
        from lumina.ingestion.interpreter import generate_interpretations
        result = generate_interpretations(
            extracted_text="ambiguous content",
            domain_physics={"id": "test"},
            max_interpretations=3,
            call_slm_fn=self._mock_slm_multi,
        )
        assert len(result) == 3
        labels = {r["label"] for r in result}
        assert labels == {"strict", "loose", "hierarchical"}

    def test_max_interpretations_limit(self):
        from lumina.ingestion.interpreter import generate_interpretations
        result = generate_interpretations(
            extracted_text="content",
            domain_physics={"id": "test"},
            max_interpretations=1,
            call_slm_fn=self._mock_slm_multi,
        )
        assert len(result) == 1

    def test_slm_failure_returns_fallback(self):
        from lumina.ingestion.interpreter import generate_interpretations

        def bad_slm(**_kw):
            raise RuntimeError("SLM offline")

        result = generate_interpretations(
            extracted_text="some text",
            domain_physics={"id": "test"},
            call_slm_fn=bad_slm,
        )
        assert len(result) == 1
        assert result[0]["confidence"] == 0.0
        assert "raw text preserved" in result[0]["ambiguity_notes"]


# ── IngestService lifecycle tests ────────────────────────────

class TestIngestService:
    """Full lifecycle: accept → extract → review → commit."""

    @staticmethod
    def _make_service(**kw):
        from lumina.ingestion.service import IngestService
        defaults = {
            "max_file_size_mb": 1,
            "call_slm_fn": lambda **_kw: json.dumps({
                "interpretations": [{
                    "label": "default",
                    "yaml_content": "module_id: m1\nartifacts: []",
                    "confidence": 0.9,
                    "ambiguity_notes": "",
                }]
            }),
        }
        defaults.update(kw)
        return IngestService(**defaults)

    # ── accept_document ──

    def test_accept_returns_doc_id(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"hello",
            filename="test.md",
            content_type="markdown",
            actor_id="user1",
            domain_id="dom1",
        )
        assert isinstance(doc_id, str)
        record = svc.get_record(doc_id)
        assert record is not None
        assert record["status"] == "pending_extraction"
        assert record["domain_id"] == "dom1"

    def test_accept_rejects_oversized(self):
        svc = self._make_service(max_file_size_mb=0)
        # 1 byte > 0 MB limit
        with pytest.raises(ValueError, match="exceeds limit"):
            svc.accept_document(
                file_bytes=b"x" * 1024,
                filename="big.md",
                content_type="markdown",
                actor_id="u",
                domain_id="d",
            )

    def test_accept_rejects_invalid_type(self):
        svc = self._make_service()
        with pytest.raises(ValueError, match="Unsupported content type"):
            svc.accept_document(
                file_bytes=b"x",
                filename="f.bin",
                content_type="binary",
                actor_id="u",
                domain_id="d",
            )

    # ── extract_interpretations ──

    def test_extract_produces_interpretations(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"data",
            filename="test.md",
            content_type="markdown",
            actor_id="user1",
            domain_id="dom1",
        )
        interps = svc.extract_interpretations(doc_id, domain_physics={"id": "dom1"})
        assert len(interps) >= 1
        assert interps[0]["label"] == "default"

        record = svc.get_record(doc_id)
        assert record["status"] == "extraction_complete"

    def test_extract_missing_doc_raises(self):
        svc = self._make_service()
        with pytest.raises(ValueError, match="not found"):
            svc.extract_interpretations("nonexistent", domain_physics={})

    # ── review_interpretation ──

    def test_review_approve(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"data",
            filename="test.md",
            content_type="markdown",
            actor_id="u1",
            domain_id="d1",
        )
        interps = svc.extract_interpretations(doc_id, domain_physics={"id": "d1"})
        interp_id = interps[0]["id"]

        result = svc.review_interpretation(
            doc_id,
            decision="approve",
            reviewer_id="da1",
            selected_interpretation_id=interp_id,
        )
        assert result["status"] == "approved"
        assert result["selected_interpretation_id"] == interp_id

    def test_review_reject(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"data",
            filename="test.md",
            content_type="markdown",
            actor_id="u",
            domain_id="d",
        )
        svc.extract_interpretations(doc_id, domain_physics={"id": "d"})

        result = svc.review_interpretation(
            doc_id, decision="reject", reviewer_id="da"
        )
        assert result["status"] == "rejected"

    def test_review_approve_requires_interpretation_id(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"d", filename="t.md", content_type="markdown",
            actor_id="u", domain_id="d",
        )
        svc.extract_interpretations(doc_id, domain_physics={"id": "d"})

        with pytest.raises(ValueError, match="selected_interpretation_id required"):
            svc.review_interpretation(doc_id, decision="approve", reviewer_id="da")

    def test_review_edit_creates_new_interpretation(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"d", filename="t.md", content_type="markdown",
            actor_id="u", domain_id="d",
        )
        svc.extract_interpretations(doc_id, domain_physics={"id": "d"})

        result = svc.review_interpretation(
            doc_id,
            decision="edit",
            reviewer_id="da",
            edits={"yaml_content": "custom: true"},
        )
        assert result["status"] == "approved"
        # The new edited interpretation should exist
        edited = [i for i in result["interpretations"] if i["label"] == "edited"]
        assert len(edited) == 1
        assert edited[0]["yaml_content"] == "custom: true"

    # ── commit_ingestion ──

    def test_commit_success(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"data", filename="t.md", content_type="markdown",
            actor_id="u", domain_id="d",
        )
        interps = svc.extract_interpretations(doc_id, domain_physics={"id": "d"})
        svc.review_interpretation(
            doc_id, decision="approve", reviewer_id="da",
            selected_interpretation_id=interps[0]["id"],
        )
        result = svc.commit_ingestion(doc_id, actor_id="da")
        assert result["status"] == "committed"
        assert "committed_hash" in result
        assert len(result["committed_hash"]) == 64  # SHA-256 hex

    def test_commit_rejects_non_approved(self):
        svc = self._make_service()
        doc_id = svc.accept_document(
            file_bytes=b"d", filename="t.md", content_type="markdown",
            actor_id="u", domain_id="d",
        )
        with pytest.raises(ValueError, match="must be 'approved'"):
            svc.commit_ingestion(doc_id, actor_id="u")

    # ── list_records ──

    def test_list_records_filtering(self):
        svc = self._make_service()
        svc.accept_document(
            file_bytes=b"a", filename="a.md", content_type="markdown",
            actor_id="u", domain_id="dom1",
        )
        svc.accept_document(
            file_bytes=b"b", filename="b.md", content_type="markdown",
            actor_id="u", domain_id="dom2",
        )

        all_records = svc.list_records()
        assert len(all_records) == 2

        dom1_only = svc.list_records(domain_id="dom1")
        assert len(dom1_only) == 1
        assert dom1_only[0]["domain_id"] == "dom1"

    def test_list_records_pagination(self):
        svc = self._make_service()
        for i in range(5):
            svc.accept_document(
                file_bytes=f"doc{i}".encode(),
                filename=f"doc{i}.md",
                content_type="markdown",
                actor_id="u",
                domain_id="d",
            )
        page = svc.list_records(limit=2, offset=0)
        assert len(page) == 2

        page2 = svc.list_records(limit=2, offset=2)
        assert len(page2) == 2


# ── Content type detection tests ─────────────────────────────

class TestContentTypeDetection:
    """Tests for _detect_content_type helper used by API endpoints."""

    def test_known_extensions(self):
        from lumina.api.server import _detect_content_type
        assert _detect_content_type("doc.pdf") == "pdf"
        assert _detect_content_type("doc.docx") == "docx"
        assert _detect_content_type("doc.doc") == "docx"
        assert _detect_content_type("doc.md") == "markdown"
        assert _detect_content_type("doc.markdown") == "markdown"
        assert _detect_content_type("doc.txt") == "markdown"
        assert _detect_content_type("doc.csv") == "csv"
        assert _detect_content_type("doc.json") == "json"
        assert _detect_content_type("doc.yaml") == "yaml"
        assert _detect_content_type("doc.yml") == "yaml"

    def test_unknown_extension(self):
        from lumina.api.server import _detect_content_type
        assert _detect_content_type("doc.exe") is None
        assert _detect_content_type("noext") is None
