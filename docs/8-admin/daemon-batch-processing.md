---
version: 2.0.0
last_updated: 2026-03-31
---

# Concept — Daemon Batch Processing

**Version:** 2.0.0  
**Status:** Active  
**Last updated:** 2026-03-31  

---

## NAME

daemon-batch-processing — load-based maintenance and enrichment tasks

## SYNOPSIS

The daemon batch processing subsystem runs maintenance, consistency, and
enrichment tasks across all domains.  Tasks are dispatched opportunistically
by the Resource Monitor Daemon when the system is idle, or manually via the
`trigger_daemon_task` admin command.

The design philosophy is **digestive**: after ingestions, chat sessions, and
domain modifications, the daemon digests accumulated changes — expanding
glossaries, pruning stale entries, checking cross-module consistency, and
rebuilding indexes.

## DESCRIPTION

### Design Principles

1. **Proposal-based** — Tasks generate proposals for DA review rather than making direct changes.  Preserves domain authority sovereignty over content.
2. **Domain-scoped** — Each task runs independently per domain, isolating failures and allowing domain-specific task selection.
3. **Idempotent** — Tasks can safely re-run without side effects.
4. **Observable** — Every run produces a report with per-task timing, success/failure status, and proposal counts.
5. **Load-aware** — The Resource Monitor Daemon dispatches tasks when system load drops below idle threshold, and preempts if load spikes.

### Task Catalog

| Task | Purpose |
|------|---------|
| `glossary_expansion` | Scans recent ingestions for terms not in the domain glossary; proposes additions |
| `glossary_pruning` | Identifies glossary entries missing definitions or no longer referenced |
| `rejection_corpus_alignment` | Validates rejection corpus entries against current module set; flags stale references |
| `cross_module_consistency` | Detects prerequisite cycles and conflicting definitions across modules |
| `knowledge_graph_rebuild` | Reindexes concepts, entities, and relationships from all modules |
| `pacing_heuristic_recompute` | Recalculates pacing parameters from accumulated session telemetry |
| `domain_physics_constraint_refresh` | Validates invariant constraints still hold after content changes |
| `slm_hint_generation` | Pre-generates SLM context hints for new content to speed inference |
| `telemetry_summary_refresh` | Rebuilds aggregate telemetry metrics for dashboard display |
| `logic_scrape_review` | Surfaces pending logic scrape proposals for DA review |
| `context_crawler` | Crawls domain modules via SLM to stage context hints for DA approval |
| `gated_staging` | Drafts glossary updates and data-stream sorts; stages all outputs for DA review — never auto-updates |
| `verify_repo` | Repository integrity checks |
| `schema_integrity` | Schema validation across domain packs |

### Proposal Workflow

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

### Configuration

Daemon settings are in `cfg/runtime-config.yaml` under the `daemon:` block:

```yaml
daemon:
  enabled: true
  poll_interval_seconds: 30
  idle_threshold: 0.20
  busy_threshold: 0.40
  idle_sustain_seconds: 60
  grace_period_seconds: 60
  task_priority:
    - knowledge_graph_rebuild
    - glossary_expansion
    - glossary_pruning
    - slm_hint_generation
    - cross_module_consistency
    - telemetry_summary_refresh
    - context_crawler
    - gated_staging
    - verify_repo
    - schema_integrity
```

### Chat Commands

- `"Trigger daemon task"` → Starts a manual batch run
- `"Daemon status"` → Shows current/last run info
- `"Review proposals"` → Lists pending proposals for the resolved domain

### Dashboard Integration

The daemon status is visible in the Governance Dashboard overview panel.
Pending proposals are listed with approve/reject actions per proposal.

## SEE ALSO

resource-monitor-daemon(7), admin-command-schemas(8)

Key differences from scheduled/manual runs:

| Concern | Scheduled / Manual | Daemon |
|---------|--------------------|--------|
| Task selection | Full task list | Single task per dispatch |
| Trigger | Cron clock or API call | Load score below idle threshold |
| Preemption | Runs to completion | Cooperative preemption if load spikes |
| Frequency | Once per schedule | As often as idle windows allow |
| Configuration | `daemon:` section in runtime-config.yaml | `daemon:` section in runtime-config.yaml |

The daemon maintains its own priority-ordered task list (`daemon.task_priority`)
which is a subset of the full task catalog.  See
[`docs/7-concepts/resource-monitor-daemon.md`](resource-monitor-daemon.md)
for the complete daemon architecture.

## Source Files

- `src/lumina/daemon/scheduler.py` — Run lifecycle, proposal management, `trigger_opportunistic()`
- `src/lumina/daemon/tasks.py` — Individual task implementations
- `src/lumina/daemon/report.py` — Report and proposal dataclasses
- `src/lumina/staging/staging_service.py` — File staging service (used by context_crawler and gated_staging)
- `src/lumina/daemon/resource_monitor.py` — Resource Monitor Daemon (load-based dispatch)
- `src/lumina/daemon/task_adapter.py` — Preemptible task execution bridge
- `src/web/components/dashboard/DashboardPage.tsx` — Dashboard UI (daemon tab)
- `domain-packs/system/cfg/runtime-config.yaml` — Daemon configuration
