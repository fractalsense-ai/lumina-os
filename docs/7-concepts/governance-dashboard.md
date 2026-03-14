# Concept — Governance Dashboard

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

## Overview

The Governance Dashboard is a React SPA route within the Lumina web interface, accessible only to users with `root` or `domain_authority` roles. It provides a centralized view for managing domain governance operations: reviewing escalations, monitoring ingestions, overseeing night cycle proposals, and observing system telemetry.

## Access Control

The dashboard navigation toggle is visible in the application header only when the authenticated user has the `root` or `domain_authority` role. Other roles (learner, guest, auditor, it_support) see only the chat interface.

## Panels

### Overview Tab

Displays aggregate system metrics:
- **CTL Records** — Total causal trace ledger entries
- **Pending Escalations** — Number of unresolved escalation events
- **Resolved Escalations** — Number of resolved escalation events
- **Domain Cards** — Per-domain summaries showing pending escalation and ingestion counts

Data is fetched from:
- `GET /api/dashboard/domains` — Domain-level summaries
- `GET /api/dashboard/telemetry` — Aggregate CTL and escalation metrics

### Escalations Tab

Lists all escalation records with status-colored badges (pending = yellow, resolved = green, deferred = blue). For pending escalations, the DA can:
- **Approve** — Resolve the escalation positively
- **Reject** — Resolve the escalation negatively
- **Defer** — Postpone the decision

Domain authorities see only escalations for their governed domains. Root users see all.

Data source: `GET /api/escalations`

### Ingestions Tab

Shows all ingestion records with their lifecycle status:
- `uploaded` (blue) → `extracted` (yellow) → `reviewed` (purple) → `committed` (green) / `rejected` (red)

Actions available at each stage:
- **Extract** — Trigger content extraction from the uploaded file
- **Review** — Generate SLM interpretations
- **Commit** — Finalize an approved interpretation

The interpretation viewer expands to show each candidate interpretation with confidence scores and YAML content preview.

Data source: `GET /api/ingest`

### Night Cycle Tab

Displays the night cycle subsystem status and pending proposals:
- **Status Card** — Enabled state, cron schedule, total runs, running indicator
- **Last Run Summary** — Status, trigger source, proposals generated, timestamp
- **Pending Proposals** — List of actionable proposals with approve/reject buttons

Data sources:
- `GET /api/nightcycle/status`
- `GET /api/nightcycle/proposals`

## Architecture

The dashboard is implemented as a set of React components within the existing SPA:

```
src/web/
  app.tsx                          — AppHeader with dashboard toggle, view routing
  components/dashboard/
    DashboardPage.tsx              — Tab container (Overview, Escalations, Ingestions, Night Cycle)
    EscalationQueue.tsx            — Escalation list and resolution actions
    IngestionReview.tsx            — Ingestion lifecycle and interpretation viewer
    NightCyclePanel.tsx            — Night cycle status and proposal management
```

No client-side router is used. The dashboard is controlled by a `view` state in the top-level `App` component that switches between `'chat'` and `'dashboard'` views.

## DA Workflow

A typical domain authority session:

1. Open the dashboard via the header navigation toggle
2. Check the **Overview** for any pending items
3. Review **Escalations** — approve, reject, or defer as needed
4. Check **Ingestions** — extract and review uploaded documents, commit approved interpretations
5. Review **Night Cycle** proposals — approve glossary additions, reject stale entries
6. Switch back to chat for conversational domain work

## Source Files

- `src/web/components/dashboard/DashboardPage.tsx` — Main dashboard container
- `src/web/components/dashboard/EscalationQueue.tsx` — Escalation management
- `src/web/components/dashboard/IngestionReview.tsx` — Ingestion review
- `src/web/components/dashboard/NightCyclePanel.tsx` — Night cycle panel
- `src/web/app.tsx` — View routing and header component
