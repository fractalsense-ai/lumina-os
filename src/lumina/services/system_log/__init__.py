"""System Log Service — append-only log, SSE streaming, audit queries.

Owns:
  - Log record queries (records, sessions, warnings, alerts)
  - Hash-chain validation
  - SSE event streaming
  - Audit log queries (scoped by role)

See docs/7-concepts/microservice-boundaries.md § System Log Service.
"""
