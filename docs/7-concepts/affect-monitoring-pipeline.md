---
version: 1.0.0
last_updated: 2026-07-17
---

# affect-monitoring-pipeline(7) — Three-layer model for tracking actor affect over time

## Name

affect-monitoring-pipeline — the layered architecture by which Lumina
observes, smooths, and reasons about an actor's emotional rhythm
across timescales ranging from a single conversational turn to weeks.

## Synopsis

Three independent layers cooperate to surface actionable affect signals
without drowning the system in transient noise:

1. **Acute envelope** — per-turn affect samples and immediate clamps.
2. **Heartbeat shape** — rolling per-axis baseline (mean + variability) over a session window.
3. **Chronic spectral** — daemon-side FFT over historical samples that detects sustained drift across multi-hour to multi-day bands.

The chronic layer surfaces findings to the in-session adapter via a
deduped, expiring **advisory** record so the adapter can mention them
once at the right moment without forcing the daemon to participate in
every turn.

## Description

### EMS triage analogy

Think of a paramedic arriving at a scene.  The acute envelope is the
quick visual sweep — is the patient alert?  Bleeding?  The heartbeat
shape is the vitals trend across the call — is the BP stabilising or
trending in a worrying direction?  The chronic spectral layer is the
patient's medical history — recurring patterns that only become visible
when you zoom out far enough.  Each layer answers a different question
on a different timescale, and each is allowed to be wrong on its own
because the others compensate.

### Layer breakdown

| Layer | Window | Where it lives | Output | Refresh cadence |
|-------|--------|----------------|--------|-----------------|
| **Acute envelope** | one turn | adapter (`journal_domain_step`) | per-turn `decision.affect_*` fields | every turn |
| **Heartbeat shape** | session/day | adapter, persisted on profile | `learning_state.global_affect_baseline` (per-axis EMA + variance proxy) | end of every turn |
| **Chronic spectral** | weeks | daemon (`rhythm_fft_analysis`) | `learning_state.spectral_advisories` (list of advisory records) + `Proposal` rows | opportunistic, idle-dispatched |

### The advisory bridge (Phase G.5)

The chronic layer emits findings while no session is in flight, so
findings need a durable carrier into the next session.  That carrier is
the **advisory record**:

```yaml
advisory_id:  uuid4
axis:         valence | arousal | salience
band:         dc_drift | circaseptan | ultradian
direction:    rising | falling
z_score:      float
message:      human-readable string
created_utc:  ISO-8601
expires_utc:  ISO-8601   # default created_utc + 24h
```

Advisories live on `profile["learning_state"]["spectral_advisories"]`
as a free-form list (the `learning_state` blob is intentionally not
schemaed at the framework level so domain packs may extend it).

#### Lifecycle invariants

1. **Dedup-by-band**: writing a new advisory for the same `(axis, band)` pair replaces the prior record rather than appending.
2. **Expire-on-read**: every read pass prunes records whose `expires_utc <= now`.
3. **Single-surface-per-session**: the adapter sets a sticky `state["session_advisory_surfaced"]` flag the first time an advisory is attached to a decision; subsequent turns in the same session do not re-surface it.
4. **Priority ordering**: when multiple active advisories exist, the adapter selects by `axis` (valence > arousal > salience) then `band` (dc_drift > circaseptan > ultradian).

#### Two surfacing entry points

- `journal_session_start(profile, ...)` — called by the orchestrator at session boot; returns the highest-priority active advisory (or `None`) for inclusion in the opening prompt context.
- `journal_domain_step(state, task, ev, ...)` — piggy-back attachment on the first ordinary turn of a session that did not call `session_start` (e.g., resumed sessions).  Same selection rule, same sticky-flag semantics.

### Data flow

```
   per-turn affect samples
            │
            ▼
   ┌──────────────────────┐
   │  Acute envelope      │ ── decision.affect_*
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  Heartbeat shape     │ ── learning_state.global_affect_baseline
   │  (per-axis EMA)      │
   └──────────┬───────────┘
              │ (persisted to profile)
              ▼
        ┌───────────┐    idle ticks
        │  Profile  │ ◄──────────────┐
        └─────┬─────┘                │
              │                ┌─────┴───────────┐
              │  reads samples │  rhythm_fft     │
              │                │  daemon task    │
              │                └─────┬───────────┘
              │                      │ writes
              │                      ▼
              │           learning_state.spectral_advisories
              │
              ▼
   ┌──────────────────────────────────────────┐
   │  Adapter advisory bridge (Phase G.5)     │
   │   • session_start → opening context      │
   │   • domain_step  → sticky piggyback      │
   └──────────────────────────────────────────┘
```

### Why three layers and not one

A single FFT-only pipeline would be too slow to react to acute distress
inside a turn.  A single envelope-only pipeline would miss week-long
mood drift entirely.  Splitting along timescale lets each layer use the
algorithm best suited to its window — clamps for acute, EMA for
heartbeat, FFT for chronic — and lets each layer fail independently
without taking the others down.

## See also

- daemon-tasks(1) — registered idle-dispatch tasks including `rhythm_fft_analysis`.
- affect-monitor(3) — public function-level API for the affect-monitor module across phases A–G.5.
- baseline-before-escalation(7) — companion gate that suppresses delta-driven escalation while the heartbeat-shape baseline is still priming.
- learning-profile(7) — shape and ownership of the `learning_state` blob.
