---
version: 1.0.1
last_updated: 2026-04-21
---

# Telemetry Sliding Window & Conversation Black Box

**Version:** 1.0.1  
**Status:** Active  
**Last updated:** 2026-04-16  

---

## NAME

telemetry-and-blackbox — Sliding-window telemetry, conversation ring buffer, and black-box snapshot system.

## Overview

Three interconnected subsystems that give Lumina a historical view of system behaviour and the ability to freeze diagnostic context when things go wrong:

1. **Telemetry Sliding Window** — Replaces point-in-time load snapshots with a bounded history, computing trajectory and curve summaries deterministically.
2. **Conversation Ring Buffer** — Dashcam-style circular buffer of the last *N* turn-pairs. Ephemeral — dies with the session.
3. **Black Box Snapshot** — When a trigger fires, freezes the ring buffer + telemetry + trace events + session state into a JSON file on disk.

## DESIGN PRINCIPLES

### Seventh Generation Telemetry

Inspired by the Iroquois Seventh Generation principle: decisions should consider their impact seven generations ahead. Point-in-time readings are snapshots; the sliding window shows *where things are headed*.

### Dashcam Analogy

An ambulance dashcam runs continuously, recording a fixed window of footage. The camera only *saves* when a kinematic trigger fires — speed exceeded, hard braking, sharp turn. The ring buffer works the same way: it always records, but only *crystallises* on trigger.

### Deterministic Math Layer

All curve computation (EWMA, trajectory classification, delta percentage, curve shape) is handled by deterministic code in `load_estimator.TelemetryWindow`. The LLM/SLM receives only a compressed JSON summary — it never computes the curves itself.

### Domain Packs Own Triggers

The core provides infrastructure and a few built-in escalation triggers. Domain packs register custom triggers via `blackbox_triggers.trigger_registry.register()`. Examples:
- `resource_runaway` — load score > 0.9
- `sudden_crash` — trajectory is `cliff_drop`
- `logic_whiplash` — invariant delta > 0.5

## ARCHITECTURE

### Telemetry Sliding Window

```
LoadEstimator.sample()
    │
    ▼
LoadSnapshot ──push──▶ TelemetryWindow (deque[maxlen=N])
                              │
                              ▼
                        TelemetrySummary
                         ├── json_summary   → SLM/LLM payload
                         └── numeric_vector → internal threshold checks
```

**EWMA** (Exponential Weighted Moving Average) with α=0.3 provides smooth curve tracking that naturally weights recent data.

**Trajectory Classification:**
- `stable` — average difference between halves < 0.05
- `rising` / `falling` — directional trend
- `spiking` — latest value far above mean with sudden jump
- `cliff_drop` — latest value far below mean with sudden drop

**Curve Shape:**
- `linear` — steady rate of change
- `exponential` — accelerating rate
- `plateau` — decelerating rate

### Conversation Ring Buffer

```
processing.process_message()
    │
    ├── call_llm() → llm_response
    │
    └── session.ring_buffer.push(user_msg, llm_response, turn, domain)
             │
             ▼
        ConversationRingBuffer (deque[maxlen=10])
             │
             └── .snapshot() → frozen list[TurnRecord]
```

The buffer is **never persisted** — it lives in `SessionContainer` and dies with the session. This respects the memory-spec prohibition on transcript retention. The only exception is when a blackbox trigger fires, at which point the buffer contents become part of the diagnostic package.

### Black Box Snapshot

```
Trigger fires (escalation / daemon / domain)
    │
    ▼
capture_blackbox()
    ├── ring_buffer.snapshot()
    ├── estimator.get_window_summary()
    ├── recent TraceEvent records
    ├── session state (task, turn, domain)
    └── system health
    │
    ▼
write_blackbox() → data/blackbox/{session}_{timestamp}.json
    │
    └── _prune_old_snapshots() if > max_files
```

**Atomic writes**: tmp file → `os.replace()` for crash safety.  
**Auto-purge**: oldest files pruned when directory exceeds `max_files` (default: 100).

## TRIGGER REGISTRY

```python
from lumina.session.blackbox_triggers import trigger_registry

# Built-in (core-provided):
# - escalation_critical: fires on critical_invariant_violation escalations
# - escalation_severe: fires when escalation targets meta/domain authority

# Domain-pack custom:
trigger_registry.register("resource_runaway", lambda e: e.get("load_score", 0) > 0.9)
```

Triggers are checked in two places:
1. **Escalation flow** — `SystemLogWriter.write_escalation_record()` checks the trigger registry with the escalation record.
2. **Daemon poll** — `ResourceMonitorDaemon._poll_once()` checks the trigger registry with telemetry state after each sample.

## CONFIGURATION

In `domain-packs/system/cfg/runtime-config.yaml`:

```yaml
daemon:
  telemetry_window_depth: 20  # Number of snapshots in the sliding window

blackbox:
  enabled: true
  buffer_size: 10             # Turn-pairs in the conversation ring buffer
  output_dir: data/blackbox
  max_files: 100              # Auto-purge oldest beyond this count
  include_trace_events: true
```

## FILES

| File | Purpose |
|------|---------|
| `src/lumina/daemon/load_estimator.py` | `TelemetryWindow`, `TelemetrySummary`, EWMA curve math |
| `src/lumina/session/ring_buffer.py` | `ConversationRingBuffer`, `TurnRecord` |
| `src/lumina/session/blackbox.py` | `BlackBoxSnapshot`, `capture_blackbox()`, `write_blackbox()` |
| `src/lumina/session/blackbox_triggers.py` | `TriggerRegistry`, built-in triggers |
| `standards/blackbox-snapshot-schema-v1.json` | JSON Schema for snapshot output |

## SEE ALSO

- [`context-is-not-conversation(7)`](context-is-not-conversation.md) — why behavioral state compression replaces transcript replay
- [`ai-governance-principles(7)`](ai-governance-principles.md) — principles 2 and 5 applied to telemetry and session memory boundaries
- [memory-spec](memory-spec.md) — explains why conversation content is not normally stored
- [resource-monitor-daemon](resource-monitor-daemon.md) — the daemon that polls telemetry
- [system-log-micro-router](system-log-micro-router.md) — trace events and escalation records
