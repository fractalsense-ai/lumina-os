# Section 3 — Functions (Library Reference)

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-12  

---

Internal library interfaces used by the Lumina runtime.

| Module | Description |
|--------|-------------|
| [auth](auth.md) | JWT creation, verification, and password hashing |
| [permissions](permissions.md) | chmod-style module permission checking |
| [persistence_adapter](persistence-adapter.md) | Abstract persistence interface |
| [runtime_loader](../../reference-implementations/runtime_loader.py) | Domain runtime configuration loader |
| [ppa_orchestrator](../../reference-implementations/ppa-orchestrator.py) | PPA orchestrator engine |
| [nlp-pre-interpreter](nlp-pre-interpreter.md) | Deterministic NLP pre-interpreter for student messages (education domain) |
| [fluency-monitor](fluency-monitor.md) | Consecutive-success fluency gate for tier advancement (education domain) |
| [problem-generator](problem-generator.md) | Tier-based algebra problem generator (education domain) |
