---
version: 1.0.0
last_updated: 2026-04-25
---

# signal-decomposition-framework(7) — Domain-agnostic signal monitoring

## Name

signal-decomposition-framework — the layered, signal-name-agnostic
machinery by which Lumina tracks any named scalar stream (human affect
axes, environmental sensors, motor vibration, lab instruments, etc.)
across acute, heartbeat-shape, and chronic spectral timescales.

## Synopsis

Domains declare their observable scalars in ``domain-physics.json``
under a top-level ``signals`` block:

```json
{
  "signals": {
    "soil_pH": {
      "label": "soil pH",
      "units": "pH",
      "range": [3.5, 9.5],
      "record_path": "metadata.sensor.value",
      "advisory_priority": 10,
      "bands": {
        "dc_drift":    {"window_days": [10, 60]},
        "circaseptan": {"window_days": [5, 9]}
      },
      "message_overrides": {
        "dc_drift,negative": "soil pH has drifted acidic — consider lime amendment."
      }
    }
  }
}
```

The ``rhythm_fft_analysis`` daemon task iterates every declared signal
on every actor profile, runs the math through ``lumina.signals``, and
writes back two things on the profile:

1. ``learning_state.signal_baselines`` — per-signal EWMA + spectral
   history (machine state, used by the next daemon pass).
2. ``learning_state.spectral_advisories`` — deduped, expiring,
   human-readable advisories (consumer state, surfaced in-session).

In-session consumers (e.g. ``journal_adapters``) call
``pull_active_advisory(profile, ...)`` to surface the highest-priority
unexpired advisory exactly once per session.

## Description

### Why decompose?

Human affect, soil chemistry, and motor health share nothing
phenomenologically but share everything *mathematically* once reduced
to a named scalar stream:

- a per-turn / per-reading sample (acute envelope),
- a rolling EWMA baseline + variance (heartbeat shape), and
- a multi-band FFT signature over a window (chronic spectral drift).

The framework instruments these three layers once, in one place
(``lumina.signals``), and lets each domain declare *which* scalars to
monitor, *where* to extract them from records (``record_path``), and
*how* to phrase the resulting advisory (``message_overrides``).

This honors the **instruments-vs-reactions** principle (see
[principles(7)](principles.md)): the framework provides the
instrument, the domain provides the meaning.

### Three layers

The chronic spectral layer is the only one daemon-owned; the acute and
heartbeat-shape layers run inline at signal-emission sites.

| Layer            | Owner          | Window        | Output |
|------------------|----------------|---------------|--------|
| Acute envelope   | domain-lib     | 1 sample      | clamp / immediate flag |
| Heartbeat shape  | domain-lib     | rolling EWMA  | sustained-run alert |
| Chronic spectral | daemon         | days–months   | advisory record |

For the historical SVA-specific framing of these layers see
[affect-monitoring-pipeline(7)](affect-monitoring-pipeline.md); the
framework documented here is the generalisation.

### The ``signals`` block contract

Each entry under ``signals`` is a
[domain-physics-schema-v1](../../standards/domain-physics-schema-v1.json)
``signal_definition``:

| Field | Required | Purpose |
|-------|----------|---------|
| ``label`` | yes | Human-readable name; substituted into advisory messages. |
| ``units`` | yes | Free-form units string (e.g. ``"pH"``, ``"counts/s"``). |
| ``range`` | yes | ``[min, max]`` plausible range; out-of-range readings discarded. |
| ``record_path`` | yes | Dotted path into a record's body where the scalar lives. |
| ``advisory_priority`` | no | Higher wins when ``pull_active_advisory`` arbitrates. |
| ``advisory_ttl_seconds`` | no | Override default 24h advisory expiry. |
| ``bands`` | no | Per-band ``window_days: [min, max]`` overrides. |
| ``message_overrides`` | no | Per ``"<band>,<direction>"`` or ``"<band>,*"`` template. |

``record_path`` is the wiring point: the daemon reads records from the
system log, walks the dotted path, and feeds the resulting scalar
through ``compute_spectral_signature``. There is no special-casing per
domain — agriculture's ``"metadata.sensor.value"`` and the assistant
SVA's ``"metadata.affect.valence"`` traverse the same code.

### The advisory schema

Persisted advisory records conform to
[spectral-advisory-schema-v1](../../standards/spectral-advisory-schema-v1.json):

```json
{
  "advisory_id": "uuid-…",
  "signal":      "soil_pH",
  "band":        "dc_drift",
  "direction":   "negative",
  "z_score":     -3.42,
  "message":     "soil pH has drifted acidic — consider lime amendment.",
  "created_utc": "2026-04-25T12:00:00Z",
  "expires_utc": "2026-04-26T12:00:00Z"
}
```

``direction`` is normalised to the symbolic vocabulary
(``"positive" | "negative" | "neutral" | "*"``) at the daemon→advisory
boundary; the underlying spectral math still emits ``+1 / -1 / 0``
internally and the daemon's ``Proposal.detail`` preserves the integer
form for backward compatibility.

### Adding a new domain

1. Declare each scalar under ``signals`` in your domain pack's
   ``domain-physics.json``.
2. If your records aren't already shaped as ``SignalSample``, add a
   ``to_signal_samples(...)`` adapter to a group library — see
   ``domain-packs/agriculture/domain-lib/sensors/environmental_sensors.py``
   for the reference pattern.
3. (Optional) Provide ``message_overrides`` for any (band, direction)
   you want to phrase domain-appropriately. Anything you don't override
   falls back to the framework's neutral template, with ``{label}``
   substituted.

The daemon task and the in-session advisory consumer require no
changes; they iterate whatever you declare.

## See Also

- [affect-monitoring-pipeline(7)](affect-monitoring-pipeline.md) — the SVA-specific instantiation
- [signals(3)](../3-functions/signals.md) — public API of ``lumina.signals``
- [domain-physics-schema-v1](../../standards/domain-physics-schema-v1.json)
- [spectral-advisory-schema-v1](../../standards/spectral-advisory-schema-v1.json)
- [principles(7)](principles.md) — instruments vs. reactions
