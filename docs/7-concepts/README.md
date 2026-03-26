---
version: 1.0.0
last_updated: 2026-03-20
---

# Section 7 — Concepts

**Version:** 1.3.0
**Status:** Active
**Last updated:** 2026-03-18

---

Architectural principles, design frameworks, and system philosophy.

| Concept | Description |
|---------|-------------|
| [principles-v1](../../specs/principles-v1.md) | Non-negotiable system principles |
| [dsa-framework-v1](../../specs/dsa-framework-v1.md) | D.S.A. structural schema (Domain, State, Actor) — the contract model behind PPA |
| [dsa-actor-model](dsa-actor-model.md) | D.S.A. Actor pillar: what an Actor is (person, sensor, device), actor types and actor groups, signal flow pipeline, distinction from RBAC roles, checklist for defining actors in new domains |
| [domain-pack-anatomy](domain-pack-anatomy.md) | What a domain pack is: bounded subject-area authority, six-component anatomy (physics / tool-adapters / runtime-adapter / NLP pre-interpreter / domain-lib / world-sim), NLP information gate, physics as standing orders, self-containment contract, cross-domain comparison |
| [hmvc-heritage](hmvc-heritage.md) | HMVC architectural lineage: how domain packs map to HMVC modules (Model = physics + schemas, Controller = controllers/, View = prompts + world-sim), self-containment as module isolation, framework-as-engine principle, adding new domains with zero engine changes |
| [rag-contracts](../../retrieval/rag-contracts.md) | RAG retrieval contract model |
| [domain-adapter-pattern](domain-adapter-pattern.md) | How domain packs extend the engine: NLP pre-processing, signal synthesis, engine contract fields, three-layer distinction (tool-adapters / domain-lib / runtime-adapter) |
| [api-server-architecture](api-server-architecture.md) | Decomposed API server module layout: thin factory, `_ModProxy` test bridge, session multi-domain isolation, glossary per-domain cache, performance profile |
| [nlp-semantic-router](nlp-semantic-router.md) | Two-tier NLP architecture: Tier 1 system-level domain classification (`classify_domain`), Tier 2 domain NLP pre-interpreter (`_nlp_anchors`), three-stage input pipeline, glossary intercept, routing surface evolution |
| [prompt-packet-assembly](prompt-packet-assembly.md) | How prompt contracts are assembled from layered components: layer reference table, input sources and telemetry, domain library tools, what the LLM sees vs. what is hidden |
| [zero-trust-architecture](zero-trust-architecture.md) | Zero-trust posture across all Lumina layers: per-layer trust enforcement matrix, NIST SP 800-207 tenet mapping, OWASP Top 10 mapping, operational implications (fail-closed defaults, escalation, pseudonymity) |
| [novel-synthesis-framework](novel-synthesis-framework.md) | Novel synthesis detection, two-key verification gate (LLM flags + domain authority confirms), model performance benchmarking via System Log telemetry, compute efficiency through glossary intercepts and grounding anchors |
| [world-sim-persona-pattern](world-sim-persona-pattern.md) | The persona pattern: how domain packs wrap domain content in a narrative identity using the three-file world-sim composition (spec + consent + mastery). Static vs. dynamic theme selection, engine contract invariant, configuration reference, and implementation checklist for new domains. |
| [ingestion-pipeline](ingestion-pipeline.md) | Document ingestion lifecycle: upload → SLM extraction → multi-interpretation review → commit. RBAC gating, chat-driven workflow, night cycle relationship. |
| [night-cycle-processing](night-cycle-processing.md) | Batch processing subsystem: glossary expansion/pruning, cross-module consistency, knowledge graph rebuild, proposal-based review workflow, configuration reference. |
| [governance-dashboard](governance-dashboard.md) | DA governance dashboard: overview telemetry, escalation queue, ingestion review, night cycle panel. Access control and workflow patterns. |
| [cross-domain-synthesis](cross-domain-synthesis.md) | Cross-domain synthesis: opt-in VLAN bridging between domains, glossary structural comparison, invariant homomorphism detection, dual-key domain authority approval. |
| [logic-scraping](logic-scraping.md) | Logic scraping: iterative LLM probing for novel synthesis discovery, feedback accumulation, yield rate tracking, domain authority review workflow. |

These documents define the foundational design philosophy of Project Lumina. All implementation decisions trace back to these concepts.
