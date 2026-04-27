---
version: 1.2.0
last_updated: 2026-04-16
---

# Section 7 — Concepts

**Version:** 1.5.0
**Status:** Active
**Last updated:** 2026-04-16

---

Architectural principles, design frameworks, and system philosophy.

| Concept | Description |
|---------|-------------|
| [principles-v1](../../specs/principles-v1.md) | Non-negotiable system principles |
| [principles](principles.md) | Principles overview (local reference) |
| [lumina-framework-ontology](lumina-framework-ontology.md) | Engine/model-pack/module ontology for the Lumina Neuro-Symbolic Systems Framework |
| [dsa-framework-v1](../../specs/dsa-framework-v1.md) | D.S.A. structural schema (Domain, State, Actor) — the contract model behind PPA |
| [dsa-framework](dsa-framework.md) | D.S.A. framework overview (local reference) |
| [dsa-actor-model](dsa-actor-model.md) | D.S.A. Actor pillar: actor types, actor groups, signal flow, distinction from RBAC roles |
| [domain-pack-anatomy](domain-pack-anatomy.md) | Seven-component model-pack anatomy, self-containment contract, cross-domain comparison |
| [hmvc-heritage](hmvc-heritage.md) | HMVC architectural lineage: model-packs as HMVC modules, framework-as-engine |
| [rag-contracts](rag-contracts.md) | RAG retrieval contract model |
| [domain-adapter-pattern](domain-adapter-pattern.md) | How model-packs extend the engine: NLP pre-processing, signal synthesis, engine contract fields |
| [domain-evidence-extension](domain-evidence-extension.md) | Domain evidence extension pattern |
| [domain-profile-spec](domain-profile-spec.md) | Domain profile specification |
| [domain-role-hierarchy](domain-role-hierarchy.md) | Domain-scoped RBAC role tiers beneath Domain Authority ceiling |
| [api-server-architecture](api-server-architecture.md) | Decomposed API server: thin factory, `_ModProxy` test bridge, session multi-domain isolation |
| [nlp-semantic-router](nlp-semantic-router.md) | Three-pass domain classifier (keyword → vector → spaCy similarity), glossary intercept |
| [prompt-packet-assembly](prompt-packet-assembly.md) | Prompt contract assembly from layered components: layer reference, what the LLM sees vs. hidden |
| [zero-trust-architecture](zero-trust-architecture.md) | Zero-trust posture: NIST SP 800-207 mapping, OWASP Top 10 mapping, fail-closed defaults |
| [novel-synthesis-framework](novel-synthesis-framework.md) | Two-key verification gate (LLM flags + DA confirms), model benchmarking via System Log |
| [world-sim-persona-pattern](world-sim-persona-pattern.md) | Persona pattern: three-file world-sim composition (spec + consent + mastery) |
| [ingestion-pipeline](ingestion-pipeline.md) | Document ingestion lifecycle: upload → SLM extraction → review → commit |
| [cross-domain-synthesis](cross-domain-synthesis.md) | Cross-domain synthesis: opt-in VLAN bridging, glossary comparison, dual-key DA approval |
| [group-libraries-and-tools](group-libraries-and-tools.md) | Domain-scoped shared resources for cross-module reuse within a model-pack |
| [edge-vectorization](edge-vectorization.md) | Per-domain vector isolation: VectorStoreRegistry, NLP Pass 1.5 vector classification |
| [execution-route-compilation](execution-route-compilation.md) | AOT compilation of domain-physics into flat O(1) lookup tables |
| [command-execution-pipeline](command-execution-pipeline.md) | Slash command execution pipeline |
| [compressed-state-pattern](compressed-state-pattern.md) | Compressed state pattern for prompt injection mitigation |
| [escalation-auto-freeze](escalation-auto-freeze.md) | Escalation auto-freeze mechanism |
| [file-generation-staging](file-generation-staging.md) | File generation staging pipeline |
| [graceful-degradation](graceful-degradation.md) | Graceful degradation patterns across all subsystems |
| [holodeck-physics-sandbox](holodeck-physics-sandbox.md) | Holodeck physics sandbox for domain testing |
| [inspection-middleware](inspection-middleware.md) | Three-stage deterministic boundary: NLP extraction → schema validation → invariant checking |
| [ledger-tier-separation](ledger-tier-separation.md) | System Log ledger tier separation |
| [memory-spec](memory-spec.md) | Memory subsystem specification |
| [microservice-boundaries](microservice-boundaries.md) | Microservice boundary definitions and extraction strategy |
| [parallel-authority-tracks](parallel-authority-tracks.md) | Parallel authority track architecture |
| [resource-monitor-daemon](resource-monitor-daemon.md) | Load-based opportunistic task scheduling with cooperative preemption |
| [slm-compute-distribution](slm-compute-distribution.md) | SLM three-role architecture: Librarian, Physics Interpreter, Command Translator |
| [state-change-commit-policy](state-change-commit-policy.md) | Every state mutation must write a System Log record before returning success |
| [system-log-micro-router](system-log-micro-router.md) | Central async log bus with level-based routing to destinations |
| [telemetry-and-blackbox](telemetry-and-blackbox.md) | Telemetry collection and blackbox snapshot subsystem |
| [telemetry-masking](telemetry-masking.md) | Telemetry masking for privacy-preserving data collection |

### Moved to other sections

| Concept | New location |
|---------|-------------|
| [learning-profile](learning-profile.md) | Moved to [`model-packs/education/docs/7-concepts/`](../../model-packs/education/docs/7-concepts/learning-profile.md) |
| [student-commons](student-commons.md) | See [`model-packs/education/docs/7-concepts/`](../../model-packs/education/docs/7-concepts/student-commons.md) |
| [daemon-batch-processing](../8-admin/daemon-batch-processing.md) | Moved to [Section 8 — Admin](../8-admin/) |
| [governance-dashboard](../8-admin/governance-dashboard.md) | Moved to [Section 8 — Admin](../8-admin/) |
| [logic-scraping](../8-admin/logic-scraping.md) | Moved to [Section 8 — Admin](../8-admin/) |
| [llm-assisted-governance-adapters](../8-admin/llm-assisted-governance-adapters.md) | Moved to [Section 8 — Admin](../8-admin/) |

These documents define the foundational design philosophy of the Lumina Framework. All implementation decisions trace back to these concepts.
