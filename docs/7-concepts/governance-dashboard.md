---
version: 1.1.0
last_updated: 2026-06-15
---

# Concept — Governance Dashboard

**Version:** 1.1.0  
**Status:** Active  
**Last updated:** 2026-06-15  

---

## Overview

The Governance Dashboard is a React SPA route within the Lumina web interface, accessible only to users with `root` or `domain_authority` roles. It provides a centralized view for managing domain governance operations: reviewing escalations, monitoring ingestions, overseeing daemon batch proposals, and observing system telemetry.

Since v1.1.0 the dashboard uses a **dynamic tab manifest** that filters visible tabs by the authenticated user's RBAC role. Tabs are defined in a `TAB_MANIFEST` array within `DashboardPage.tsx`. Real-time events are delivered via the SSE event stream (`GET /api/events/stream`).

## Access Control

The dashboard navigation toggle is visible in the application header only when the authenticated user has the `root` or `domain_authority` role. Other roles (learner, guest, auditor, it_support) see only the chat interface.

A notification badge appears on the Dashboard button in the chat view, showing the count of unread SSE events received while the user is in the chat interface. Navigating to the dashboard clears the unread count.

## Panels

### Overview Tab

Displays aggregate system metrics:
- **System Log Records** — Total system logs entries
- **Pending Escalations** — Number of unresolved escalation events
- **Resolved Escalations** — Number of resolved escalation events
- **Domain Cards** — Per-domain summaries showing pending escalation and ingestion counts

Data is fetched from:
- `GET /api/dashboard/domains` — Domain-level summaries
- `GET /api/dashboard/telemetry` — Aggregate System Log and escalation metrics

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

### Daemon Batch Tab

Displays the daemon batch subsystem status and pending proposals:
- **Status Card** — Enabled state, load score, total runs, running indicator
- **Last Run Summary** — Status, trigger source, proposals generated, timestamp
- **Pending Proposals** — List of actionable proposals with approve/reject buttons

Data sources:
- `GET /api/health/load`
- `GET /api/admin/command/staged` (filtered to daemon proposals)

### Staged Commands Tab

Lists all HITL-staged admin commands split into pending and resolved groups. For pending commands, authorized users can:
- **Accept** — Execute the staged command
- **Reject** — Discard the staged command

Pending commands display with a yellow left border. Commands expire after `LUMINA_STAGED_CMD_TTL_SECONDS` seconds.

Data source: `GET /api/admin/command/staged`

### System Logs Tab

Filtered log viewer with three filter modes: All / Warnings / Alerts. Displays record type, summary, and timestamp with color-coded badges.

Data sources:
- `GET /api/system-log/records` (all)
- `GET /api/system-log/warnings` (warnings)
- `GET /api/system-log/alerts` (alerts)

### Daemon Monitor Tab

Displays the Resource Monitor Daemon status: load score (progress bar with green/yellow/red thresholds), daemon state badge, current task, poll interval, and idle-since timestamp. Auto-refreshes every 15 seconds.

Data sources:
- `GET /api/health/load` (root, auditor)
- `GET /api/health` (fallback)

## Chat Action Cards

When the processing pipeline produces an escalation or the admin staging endpoint creates a HITL command, the response includes a `structured_content` field conforming to `standards/action-card-schema-v1.json`. The frontend renders these as interactive **ActionCard** components inline within the chat thread.

Two card types:
- **escalation** — Approve / Reject / Defer actions; resolves via `POST /api/escalations/{id}/resolve`
- **command_proposal** — Accept / Reject / Modify actions; resolves via `POST /api/admin/command/{id}/resolve`

Cards display with a colored left border (yellow for escalation, blue for command proposal) and transition to a muted resolved state after an action is taken.

## SSE Event Stream

Real-time events from the log bus are delivered to connected clients via Server-Sent Events at `GET /api/events/stream`. Authentication uses a short-lived single-use token obtained from `GET /api/events/token` (because `EventSource` cannot set Authorization headers).

The `useEventStream` React hook manages token acquisition, EventSource connection, event tracking (max 200 in memory), unread count, and auto-reconnect after 5 seconds on error.

## Architecture

The dashboard is implemented as a set of React components within the existing SPA:

```
src/web/
  app.tsx                          — AppHeader with dashboard toggle + unread badge, view routing
  hooks/
    useEventStream.ts              — SSE connection, token auth, event tracking
  components/
    ActionCard.tsx                  — Inline action card for chat (escalation / command proposal)
    dashboard/
      DashboardPage.tsx            — Dynamic tab container (TAB_MANIFEST with role-based visibility)
      EscalationQueue.tsx          — Escalation list and resolution actions
      IngestionReview.tsx          — Ingestion lifecycle and interpretation viewer
      DaemonPanel.tsx              — Daemon status and proposal management
      StagedCommandsPanel.tsx      — HITL staged command list with accept/reject
      SystemLogPanel.tsx           — Filtered system log viewer (all/warnings/alerts)
      DaemonMonitorPanel.tsx       — Resource Monitor Daemon status display
```

No client-side router is used. The dashboard is controlled by a `view` state in the top-level `App` component that switches between `'chat'` and `'dashboard'` views.

## DA Workflow

A typical domain authority session:

1. Open the dashboard via the header navigation toggle
2. Check the **Overview** for any pending items
3. Review **Escalations** — approve, reject, or defer as needed
4. Check **Ingestions** — extract and review uploaded documents, commit approved interpretations
5. Review **Daemon Batch** proposals — approve glossary additions, reject stale entries
6. Switch back to chat for conversational domain work

## Source Files

- `src/web/components/dashboard/DashboardPage.tsx` — Main dashboard container
- `src/web/components/dashboard/EscalationQueue.tsx` — Escalation management
- `src/web/components/dashboard/IngestionReview.tsx` — Ingestion review
- `src/web/components/dashboard/DaemonPanel.tsx` — Daemon panel
- `src/web/components/dashboard/StagedCommandsPanel.tsx` — Staged command management
- `src/web/components/dashboard/SystemLogPanel.tsx` — System log viewer
- `src/web/components/dashboard/DaemonMonitorPanel.tsx` — Daemon status monitor
- `src/web/components/ActionCard.tsx` — Chat action card component
- `src/web/hooks/useEventStream.ts` — SSE event stream hook
- `src/web/app.tsx` — View routing and header component
- `src/lumina/api/routes/events.py` — SSE token and stream endpoints
- `src/lumina/api/structured_content.py` — Action card builder factories
- `standards/action-card-schema-v1.json` — JSON Schema for action cards
