"""
extractors.py — Document format extractors for the ingestion pipeline.

Converts uploaded files into plain text for SLM interpretation.
Supports: PDF, DOCX, Markdown/plain-text, CSV, JSON, YAML.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

log = logging.getLogger("lumina-ingestion")


def extract_text(file_bytes: bytes, content_type: str) -> str:
    """Dispatch to the appropriate extractor based on *content_type*.

    Returns extracted plain text.  Raises ``ValueError`` for unsupported
    formats and ``RuntimeError`` when optional dependencies are missing.
    """
    extractor = _EXTRACTORS.get(content_type)
    if extractor is None:
        raise ValueError(f"Unsupported content type: {content_type!r}")
    return extractor(file_bytes)


def extract_structured(file_bytes: bytes, content_type: str) -> dict[str, Any]:
    """For JSON/YAML inputs, parse directly into a dict (pass-through)."""
    if content_type == "json":
        return json.loads(file_bytes.decode("utf-8"))
    if content_type == "yaml":
        # Use the project's yaml_loader for safety
        from lumina.core.yaml_loader import load_yaml_string

        return load_yaml_string(file_bytes.decode("utf-8"))
    raise ValueError(f"extract_structured only supports json/yaml, got {content_type!r}")


# ── Format-specific extractors ────────────────────────────────


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "pdfplumber is required for PDF ingestion. "
            "Run: pip install pdfplumber"
        )
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def _extract_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "python-docx is required for DOCX ingestion. "
            "Run: pip install python-docx"
        )
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_markdown(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


def _extract_csv(file_bytes: bytes) -> str:
    text = file_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows: list[str] = []
    for row in reader:
        rows.append(" | ".join(row))
    return "\n".join(rows)


def _extract_json(file_bytes: bytes) -> str:
    data = json.loads(file_bytes.decode("utf-8"))
    return json.dumps(data, indent=2, ensure_ascii=False)


def _extract_yaml(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


_EXTRACTORS: dict[str, Any] = {
    "pdf": _extract_pdf,
    "docx": _extract_docx,
    "markdown": _extract_markdown,
    "csv": _extract_csv,
    "json": _extract_json,
    "yaml": _extract_yaml,
}
