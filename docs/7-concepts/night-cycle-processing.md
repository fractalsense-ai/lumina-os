# Concept — Night Cycle Processing

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

## Overview

The night cycle is a batch processing subsystem that runs maintenance, consistency, and enrichment tasks across all domains. It operates on a configurable schedule (default: daily at 02:00 UTC) and can also be triggered manually by domain authorities or root users.

The design philosophy is **digestive**: after a day of ingestions, chat sessions, and domain modifications, the night cycle "digests" the accumulated changes — expanding glossaries, pruning stale entries, checking cross-module consistency, and rebuilding indexes.

## Design Principles

1. **Proposal-based** — Tasks generate proposals for DA review rather than making direct changes. This preserves domain authority sovereignty over content.
2. **Domain-scoped** — Each task runs independently per domain, isolating failures and allowing domain-specific task selection.
3. **Idempotent** — Tasks can safely re-run without side effects. Running the same task twice produces the same proposals.
4. **Observable** — Every run produces a `NightCycleReport` with per-task timing, success/failure status, and proposal counts.

## Task Catalog

| Task | Purpose |
|------|---------|
| `glossary_expansion` | Scans recent ingestions for terms not in the domain glossary; proposes additions |
| `glossary_pruning` | Identifies glossary entries missing definitions or no longer referenced |
| `rejection_corpus_alignment` | Validates rejection corpus entries against current module set; flags stale references |
| `cross_module_consistency` | Detects prerequisite cycles and conflicting definitions across modules |
| `knowledge_graph_rebuild` | Reindexes concepts, entities, and relationships from all modules |
| `pacing_heuristic_recompute` | Recalculates pacing parameters from accumulated session telemetry |
| `domain_physics_constraint_refresh` | Validates invariant constraints still hold after content changes |
| `slm_hint_generation` | Pre-generates SLM context hints for new content to speed daytime inference |
| `telemetry_summary_refresh` | Rebuilds aggregate telemetry metrics for dashboard display |

## Proposal Workflow

```
Task generates Proposal → Proposal stored as "pending"
                         → DA reviews via Dashboard or Chat
                         → DA approves → changes applied
                         → DA rejects → proposal archived
```

Each proposal contains:
- `proposal_id` — Unique identifier
- `task` — Which task generated it
- `domain_id` — Target domain
- `proposal_type` — Category (e.g., `glossary_add`, `glossary_prune`, `prerequisite_cycle`)
- `summary` — Human-readable description
- `detail` — Structured data for the proposed change
- `status` — `pending` | `approved` | `rejected`

## Configuration

Night cycle settings are in `cfg/system-runtime-config.yaml`:

```yaml
night_cycle:
  enabled: true
  schedule: "0 2 * * *"     # cron: 2 AM daily
  manual_trigger: true       # allow DA/root to trigger via API/chat
  tasks:
    - glossary_expansion
    - glossary_pruning
    - rejection_corpus_alignment
    - cross_module_consistency
    - knowledge_graph_rebuild
    - pacing_heuristic_recompute
    - domain_physics_constraint_refresh
    - slm_hint_generation
    - telemetry_summary_refresh
  max_duration_minutes: 240
  notify_on_completion: true
```

## API Endpoints

| Method | Path | RBAC | Description |
|--------|------|------|-------------|
| `POST` | `/api/nightcycle/trigger` | root, domain_authority | Manually trigger a run |
| `GET` | `/api/nightcycle/status` | root, domain_authority, auditor | Current/last run status |
| `GET` | `/api/nightcycle/report/{run_id}` | root, domain_authority | Detailed run report |
| `GET` | `/api/nightcycle/proposals` | root, domain_authority | List pending proposals |
| `POST` | `/api/nightcycle/proposals/{id}/resolve` | root, domain_authority | Approve/reject a proposal |

## Chat Commands

- `"Trigger night cycle"` → Starts a manual run
- `"Night cycle status"` → Shows current/last run info
- `"Review proposals"` → Lists pending proposals for the resolved domain

## Dashboard Integration

The Night Cycle tab in the Governance Dashboard displays:
- Current status (enabled, schedule, running state)
- Last run summary (status, trigger source, proposal count, timestamp)
- Pending proposals list with approve/reject actions per proposal

## Source Files

- `src/lumina/nightcycle/scheduler.py` — Run lifecycle and proposal management
- `src/lumina/nightcycle/tasks.py` — Individual task implementations
- `src/lumina/nightcycle/report.py` — Report and proposal dataclasses
- `src/web/components/dashboard/NightCyclePanel.tsx` — Dashboard UI component
- `cfg/system-runtime-config.yaml` — Night cycle configuration
