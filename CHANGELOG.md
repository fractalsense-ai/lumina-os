# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project uses two version tracks:

- **Implementation** (`pyproject.toml`) — tracks the software. Currently pre-1.0.
- **Specification** (`standards/lumina-core-v1.md`) — tracks the formal spec. Currently 1.1.0.

They intentionally diverge: the specification leads, the implementation follows.

---

## [0.1.0] — 2026-04-16

### Added

- **D.S.A. Framework** — Domain, State, Actor structural schema with four decision tiers (ok/minor/major/escalate)
- **Prompt Packet Assembly (PPA)** — 9-layer prompt contract assembly engine with TCP/IP-style layering
- **Inspection Middleware** — three-stage deterministic boundary (NLP extraction → schema validation → invariant checking)
- **SLM Compute Tier** — three-role SLM layer (Librarian, Physics Interpreter, Command Translator) with graceful degradation
- **Novel Synthesis Tracking** — two-key verification gate (LLM flags + Domain Authority confirms)
- **Slash Commands** — deterministic command execution bypassing the LLM entirely, three tiers (user/domain/admin)
- **Domain Pack Architecture** — self-contained domain packs with seven-component anatomy (physics, tool-adapters, runtime-adapter, NLP pre-interpreter, domain-lib, group-libraries, world-sim)
- **NLP Semantic Router** — three-pass domain classifier (keyword → vector → spaCy similarity)
- **Edge Vectorization** — per-domain vector isolation with VectorStoreRegistry
- **Execution Route Compilation** — AOT compilation of domain-physics into flat O(1) lookup tables
- **Resource Monitor Daemon** — load-based opportunistic task scheduling with cooperative preemption
- **Document Ingestion Pipeline** — SLM-driven content extraction and domain-physics generation
- **System Log** — append-only audit ledger with micro-router (DEBUG → rolling archive, AUDIT → immutable ledger)
- **Fractal Governance** — macro/meso/micro authority hierarchy with System Log accountability
- **Domain Role Hierarchy** — domain-scoped RBAC role tiers beneath Domain Authority ceiling
- **JWT Authentication** — dual-secret architecture (admin/user tier separation) with domain role claims
- **Persistence Layer** — SQLite, filesystem, and null adapters with key-based profile support
- **Three domain packs** — Education (algebra + world-sim + MUD builder), Agriculture (sensor ops + group libraries), System (SLM-only routing)
- **Web UI** — Vite + React reference frontend with PluginRegistry for domain-specific UI contributions
- **Test suite** — 3690+ pytest tests covering orchestrator, middleware, persistence, API, and domain packs
- **Documentation** — UNIX man-page convention (sections 1–8) with SHA-256 integrity tracking via MANIFEST.yaml
