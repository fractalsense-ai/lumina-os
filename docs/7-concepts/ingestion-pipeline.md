# Concept — Document Ingestion Pipeline

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

## Overview

The document ingestion pipeline enables domain authorities (DAs) to upload external content — PDFs, DOCX files, Markdown, CSV, JSON, and YAML — and transform it into structured domain-physics YAML via SLM-driven interpretation. The pipeline is RBAC-gated: only `root`, `domain_authority`, and `it_support` roles may upload; the `guest` role is explicitly excluded.

## Lifecycle

```
Upload → Content Extraction → SLM Interpretation → DA Review → Commit
```

### 1. Upload (`POST /api/ingest/upload`)

The DA uploads a file with a target `domain_id`. The system:
- Validates file size (configurable, default 10 MB max)
- Detects content type from extension and MIME type
- Creates an `IngestionRecord` in the CTL ledger with status `uploaded`
- Returns the record ID for subsequent operations

### 2. Content Extraction (`POST /api/ingest/{id}/extract`)

The system extracts raw text from the uploaded document using format-specific extractors:

| Format   | Extractor         | Dependencies     |
|----------|-------------------|------------------|
| PDF      | `pdfplumber`      | `pdfplumber`     |
| DOCX     | `python-docx`     | `python-docx`    |
| Markdown | Built-in parser   | None             |
| CSV      | `csv` stdlib      | None             |
| JSON     | `json` stdlib     | None             |
| YAML     | `yaml.safe_load`  | `pyyaml`         |

After extraction, status transitions to `extracted`.

### 3. SLM Interpretation (`POST /api/ingest/{id}/review`)

The SLM Extractor role generates **multiple candidate interpretations** of the extracted content. Each interpretation includes:
- A structured YAML representation mapping content to domain-physics concepts
- A confidence score (0.0–1.0)
- Extraction metadata (extraction strategy, model, timestamp)

Multiple interpretations allow the DA to choose the best fit or request re-extraction. Status transitions to `reviewed`.

### 4. DA Review

The DA reviews interpretations through either:
- **Dashboard UI** — The Ingestions tab in the Governance Dashboard shows all records with status badges, expandable interpretation viewers, and approve/reject buttons
- **Chat commands** — `review ingestion <id>`, `approve interpretation <id> <index>`

### 5. Commit (`POST /api/ingest/{id}/commit`)

Once an interpretation is approved, the DA commits it. The system:
- Appends a finalized CTL record with status `committed`
- The approved YAML content becomes available for domain-physics integration
- Status transitions to `committed`

## RBAC Gating

The ingestion pipeline uses the `INGEST` permission (octal bit 8) which is ACL-only — it does not appear in the standard chmod group/other fields. Domain-scoped ACL entries control per-domain ingestion access.

| Role             | Upload | Extract | Review | Commit |
|------------------|--------|---------|--------|--------|
| root             | ✅      | ✅       | ✅      | ✅      |
| domain_authority | ✅      | ✅       | ✅      | ✅      |
| it_support       | ✅      | ✅       | ❌      | ❌      |
| learner          | ❌      | ❌       | ❌      | ❌      |
| guest            | ❌      | ❌       | ❌      | ❌      |

## Chat-Driven Workflow

All ingestion operations are accessible through natural language commands interpreted by the SLM Command Translator:

- `"List ingestions"` → `list_ingestions`
- `"Review ingestion abc-123"` → `review_ingestion`
- `"Approve interpretation abc-123 index 0"` → `approve_interpretation`
- `"Reject ingestion abc-123"` → `reject_ingestion`

## Night Cycle Relationship

After heavy ingestion days, the night cycle runs `glossary_expansion` to scan committed ingestions for new terms not yet in the domain glossary, and `rejection_corpus_alignment` to ensure rejection-corpus entries remain consistent with newly ingested content.

## CTL Integration

Each ingestion creates an `IngestionRecord` in the Causal Trace Ledger. The record schema is defined in `ledger/ingestion-record-schema.json` and tracks:
- Source file metadata (name, size, content type, hash)
- Extraction results
- Interpretations with confidence scores
- Review decisions and commit status

## Source Files

- `src/lumina/ingestion/service.py` — Lifecycle orchestrator
- `src/lumina/ingestion/extractors.py` — Format-specific text extractors
- `src/lumina/ingestion/interpreter.py` — SLM-driven interpretation generator
- `ledger/ingestion-record-schema.json` — CTL record schema
- `src/web/components/dashboard/IngestionReview.tsx` — Dashboard UI component
