---
version: 1.0.0
last_updated: 2026-03-20
---

# System Log Micro-Router

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-20  

---

## NAME

system-log-micro-router — level-based event routing for the Lumina System Log subsystem

## SYNOPSIS

Every Lumina subsystem emits a **Universal Event Payload** into a central async log bus.  The **Micro-Router** inspects the event's `level` and `category` tags, then routes the event to the appropriate destination — rolling archives, admin dashboard queue, immediate alert stream, or the immutable audit ledger.

No module decides *where* its log goes.  It shouts into the void; the router catches the shout and sorts the mail.

---

## DESCRIPTION

### A. Design Principle

The System Log Micro-Router decouples all Lumina modules from knowing where log output ends up.  Before the micro-router, each module decided its own persistence strategy (append to JSONL, call a callback, etc.).  With the micro-router, every module emits a single envelope — the `LogEvent` — and the routing layer handles the rest.

> **Analogy:** a mail sorting room.  Every department drops envelopes into one slot.  The sorting room reads the address label and routes each envelope to the correct outbound bin.

This design follows the same zero-trust principle as the rest of the D.S.A. framework: no module trusts that it knows the right destination.  The router is the single authority on routing policy.

### B. Universal Event Payload

Every event is a frozen `LogEvent` dataclass:

| Field       | Type              | Description                                                     |
|-------------|-------------------|-----------------------------------------------------------------|
| `timestamp` | `str`             | ISO-8601 UTC timestamp (auto-filled by `create_event`).         |
| `source`    | `str`             | Dotted module name (e.g. `ppa_orchestrator`, `slm_ppa_worker`). |
| `level`     | `LogLevel`        | Routing tier: DEBUG, INFO, WARNING, ERROR, CRITICAL, AUDIT.     |
| `category`  | `str`             | Free-form tag for additional filtering.                         |
| `message`   | `str`             | Human-readable summary.                                         |
| `data`      | `dict`            | Arbitrary structured payload (metrics, IDs, etc.).               |
| `record`    | `dict` or `None`  | Hash-chained System Log record when `level` is AUDIT.           |

The `category` tag allows fine-grained filtering by subscribers:

- `invariant_check` — invariant evaluation results
- `session_lifecycle` — session open/close/turn events
- `hash_chain` — audit ledger writes
- `inference_parsing` — SLM enrichment results
- `rbac_change` — role or permission mutations
- `admin_command` — admin command execution
- `daemon_lifecycle` — resource monitor daemon start/stop/state transitions
- `daemon_dispatch` — opportunistic task dispatch and completion
- `daemon_preemption` — cooperative preemption events

### C. Log Bus

The `log_bus` module is the central async event bus:

```
┌─────────────┐     emit()      ┌──────────────┐    dispatch     ┌───────────────┐
│  PPA Orch   │ ──────────────► │              │ ──────────────► │ Archive Route │
│  SLM Worker │                 │   Log Bus    │                 │ Staging Route │
│  Log Writer │                 │ (asyncio.Q)  │                 │ Immediate Rte │
│  Any Module │                 │              │                 │ Audit Route   │
└─────────────┘                 └──────────────┘                 └───────────────┘
       │                               ▲
       │  emit_async()                 │
       └───────────────────────────────┘
```

- **`emit(event)`** — sync-safe wrapper for callers not in an async context (PPA orchestrator, SystemLogWriter).  Uses `call_soon_threadsafe` when emitting from a running event loop.
- **`emit_async(event)`** — async version for callers already in an async context (SLM PPA worker).
- **`subscribe(callback, level_filter, category_filter)`** — register a handler that will be called for matching events.
- **`start()` / `stop()`** — lifecycle tied to FastAPI startup/shutdown hooks.

When the bus is not running (e.g. in unit tests), `emit()` is a silent no-op.  Modules do not need to check whether the bus is alive.

### D. Routing Rules

The micro-router registers four route handlers on the bus at startup:

| Level            | Route            | Destination                                              |
|------------------|------------------|----------------------------------------------------------|
| DEBUG, INFO      | `_route_archive` | Rolling log files via Python `logging`                   |
| WARNING          | `_route_staging` | Admin dashboard queue (`WarningStore`, in-memory deque)  |
| ERROR, CRITICAL  | `_route_immediate` | Persistent error log + alert queue (`AlertStore`)      |
| AUDIT            | `_route_audit`   | Observation only — the ledger write is done by `SystemLogWriter` |

The AUDIT route does **not** perform the JSONL append.  The `SystemLogWriter` remains the "hash authority" — it chains, appends, and then emits an AUDIT event so secondary consumers can observe the write.

### E. Dashboard & Alert Stores

Two bounded in-memory stores hold recent operational events:

- **`WarningStore`** — `collections.deque(maxlen=1000)`, queryable via `GET /api/system-log/warnings`.
- **`AlertStore`** — `collections.deque(maxlen=100)`, queryable via `GET /api/system-log/alerts`.

Both return events most-recent-first and support pagination (`limit`, `offset`).  The warning store also supports `category` filtering.

### F. Integration Points

| Module                | Event Levels Emitted        | Category                |
|-----------------------|-----------------------------|-------------------------|
| `SystemLogWriter`     | AUDIT                       | `hash_chain`            |
| `PPAOrchestrator`     | INFO, WARNING               | `session_lifecycle`, `invariant_check` |
| `slm_ppa_worker`      | INFO, WARNING               | `inference_parsing`     |
| `ResourceMonitorDaemon` | INFO, WARNING             | `daemon_lifecycle`, `daemon_dispatch`, `daemon_preemption` |

### G. Lifecycle

```
FastAPI startup:
  1. log_router.start()   — registers route handlers on the bus
  2. log_bus.start()       — starts the asyncio dispatch loop
  3. slm_ppa_worker.start() — starts the SLM enrichment worker

FastAPI shutdown:
  1. slm_ppa_worker.stop()
  2. log_bus.stop()        — drains remaining events, stops loop
  3. log_router.stop()
```

---

## FILES

| Path                                          | Purpose                              |
|-----------------------------------------------|--------------------------------------|
| `src/lumina/system_log/event_payload.py`      | LogLevel, LogEvent, create_event     |
| `src/lumina/system_log/log_bus.py`            | Async event bus                      |
| `src/lumina/system_log/log_router.py`         | Micro-router route handlers          |
| `src/lumina/system_log/alert_store.py`        | WarningStore, AlertStore             |

## API ENDPOINTS

| Method | Path                          | Description                         |
|--------|-------------------------------|-------------------------------------|
| GET    | `/api/system-log/warnings`    | Query recent WARNING events         |
| GET    | `/api/system-log/alerts`      | Query recent ERROR/CRITICAL events  |

## H. Ledger Tier Paths

In addition to the severity-based routing described above, persisted records are
written to a **3-tier directory layout** that mirrors the HMVC hierarchy:

| Tier   | Path pattern                                        |
|--------|-----------------------------------------------------|
| System | ``system/session-{session_id}.jsonl``               |
| Domain | ``domains/{domain_id}/domain.jsonl``                |
| Module | ``domains/{domain_id}/modules/{module_id}.jsonl``   |

The tier is determined by record type and scope — see
[Ledger Tier Separation](ledger-tier-separation.md) for the full
classification rules and migration instructions.

---

## SEE ALSO

- `standards/system-log-v1.md` — System Log record format and hash-chaining spec
- `docs/7-concepts/prompt-packet-assembly.md` — PPA pipeline overview
- `docs/7-concepts/slm-compute-distribution.md` — SLM compute distribution
- `docs/7-concepts/ledger-tier-separation.md` — 3-tier ledger directory layout

## HISTORY

- **v1.1.0** (2026-03-20): Added ledger tier path section (H) and reference to tier separation docs.
- **v1.0.0** (2026-03-20): Initial implementation — Universal Event Payload, log bus, micro-router, dashboard/alert stores.
