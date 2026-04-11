"""Ingestion Service — upload, extraction, staged review, commit.

Owns:
  - File upload and content extraction
  - Staged review workflow (create, review, approve, reject)
  - Commit to domain packs

See docs/7-concepts/microservice-boundaries.md § Ingestion Service.
"""
