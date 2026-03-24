---
version: 1.0.0
last_updated: 2026-03-24
---

# Telemetry Masking — The Black Box Protocol

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-24  

---

## NAME

telemetry-masking — field-level data masking for the Lumina log bus

## SYNOPSIS

Every `LogEvent` passing through the log bus may be **masked** before
reaching subscribers.  Masking transforms sensitive fields according to a
declarative JSON policy — the same policy that governs what is safe to
archive, transmit, or surface on dashboards.

Toggle: `LUMINA_TELEMETRY_MASKING_ENABLED=true`  
Policy schema: `standards/telemetry-masking-schema-v1.json`

---

## DESCRIPTION

### A. Design Principle

No subscriber should ever receive PII, secrets, or content-sensitive data
that it has no authority to observe.  Rather than trusting each subscriber
to filter, the masking layer sits in the **emit** path — before events
enter the async queue — ensuring that raw payloads never leave the emit
boundary.

The masking function is **pure**: it accepts a `LogEvent` and a
`MaskingPolicy`, and returns a new `LogEvent` with sensitive fields
transformed.  The original event is never mutated.

### B. Strategies

| Strategy          | Reversible | Description |
|-------------------|:----------:|-------------|
| `pass`            | n/a        | No transformation — field passes through unchanged. |
| `sha256_hash`     | No         | One-way SHA-256 digest of the string value. |
| `hmac_pseudonym`  | With key   | Keyed HMAC-SHA256 producing a stable pseudonym. Same input always yields the same output within a key epoch. Falls back to `sha256_hash` if `LUMINA_TELEMETRY_HMAC_KEY` is unset. |
| `redact`          | No         | Replaces the value with `[REDACTED]`. |
| `truncate`        | No         | Keeps the first *N* characters, appends `…`. |

### C. Sensitivity Levels

| Level          | Intent |
|----------------|--------|
| `public`       | Safe for any audience; no masking needed. |
| `internal`     | Organisation-visible; may appear in dashboards. |
| `confidential` | Role-gated; visible only to authorised consumers. |
| `restricted`   | PII or secrets; must always be masked before dispatch. |

### D. Path Matching

Rules target fields via dot-delimited paths into the `LogEvent` dict:

- `data.user_id` — exact match.
- `data.*` — single-level wildcard (matches `data.email` but not `data.nested.field`).
- `data.**.secret` — recursive wildcard (matches `data.x.y.secret`).

Rules are evaluated **top-to-bottom**; the first matching rule wins.

### E. Hash-Chain Integrity

The `record` field on AUDIT-level events carries the hash-chained System
Log record.  **Masking never touches the `record` field** because altering
it would break the SHA-256 chain — a violation of Lumina's immutability
invariant.

---

## ENVIRONMENT

| Variable | Default | Purpose |
|----------|---------|---------|
| `LUMINA_TELEMETRY_MASKING_ENABLED` | `false` | Master toggle. Set `true` to activate masking on emit. |
| `LUMINA_TELEMETRY_HMAC_KEY` | *(unset)* | Secret key for `hmac_pseudonym` strategy. When unset, HMAC falls back to `sha256_hash`. |

---

## FILES

| Path | Description |
|------|-------------|
| `standards/telemetry-masking-schema-v1.json` | JSON Schema defining masking policy format. |
| `src/lumina/system_log/telemetry_mask.py` | Implementation — `mask_event()`, `apply_masking()`, policy loader. |
| `src/lumina/system_log/log_bus.py` | Integration point — `emit()` and `emit_async()` call `apply_masking()`. |

---

## EXAMPLES

### Minimal policy (redact all PII in `data.*`)

```json
{
  "schema_id": "lumina:telemetry-masking:v1",
  "version": "1.0.0",
  "fields": [
    { "path": "data.user_id",  "sensitivity": "restricted", "strategy": "hmac_pseudonym" },
    { "path": "data.email",    "sensitivity": "restricted", "strategy": "redact" },
    { "path": "data.password", "sensitivity": "restricted", "strategy": "redact" }
  ],
  "default_strategy": "pass"
}
```

### Loading a policy at startup

```python
import json
from lumina.system_log.telemetry_mask import load_policy_from_dict, set_active_policy

with open("my-policy.json") as f:
    policy = load_policy_from_dict(json.load(f))

set_active_policy(policy)
# Now every emit() call will apply masking automatically.
```

---

## SEE ALSO

- `system-log-micro-router(7)` — event routing architecture.
- `zero-trust-architecture(7)` — security boundaries.
- `standards/telemetry-masking-schema-v1.json` — policy schema.
