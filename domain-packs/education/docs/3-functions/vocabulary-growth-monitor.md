# vocabulary-growth-monitor(3)

## NAME

`vocabulary_growth_monitor_v0_1.py` — Passive vocabulary complexity tracker for student growth measurement

## SYNOPSIS

```python
from vocabulary_growth_monitor_v0_1 import vocabulary_growth_step

state, decision = vocabulary_growth_step(state, evidence, params)
```

## DESCRIPTION

`vocabulary_growth_monitor_v0_1.py` is an education domain-lib component that tracks **vocabulary complexity growth** across student sessions. It receives pre-computed complexity scores from the client-side analyzer (no transcript content is processed server-side), maintains a rolling baseline, and produces a non-negative growth delta.

The vocabulary monitor runs as a **secondary** state monitor alongside the ZPD monitor and fluency tracker. It is wired into free-form modules (Student Commons) via `freeform_domain_step()` in `controllers/freeform_adapters.py`. The monitor never reduces a student's score — growth delta is always `max(0, current - baseline)`.

**Design constraints:**

- No ML models; score computation happens client-side (`vocabularyAnalyzer.ts`)
- No transcript content is processed or stored server-side
- Only structured metrics flow through this module
- Growth delta is always non-negative (no punishment for regression)
- Baseline locks after N sessions to provide a stable reference

**Decision outcomes:**

| Condition | `vocab_growth_delta` | `measurement_valid` |
|-----------|---------------------|---------------------|
| Valid score, above baseline | Positive (score − baseline) | `True` |
| Valid score, at or below baseline | `0.0` | `True` |
| Score missing, invalid, or insufficient turns | `0.0` | `False` |

This module conforms to the domain-state-lib contract: deterministic, structured I/O, no free text, same inputs → same outputs.

---

## DATA TYPES

### Vocabulary tracking state

The monitor operates on the `vocabulary_tracking` section of the student's learning state (see [`learning-profile(7)`](../../../../docs/7-concepts/learning-profile.md)):

| Field | Type | Description |
|-------|------|-------------|
| `baseline_complexity` | `float \| None` | Locked baseline score (average of first N sessions) |
| `current_complexity` | `float \| None` | Most recent complexity score |
| `growth_delta` | `float` | Current growth above baseline (always ≥ 0) |
| `domain_vocabulary` | `dict` | Per-module term acquisition tracking (`{module_id: {terms_acquired, complexity_delta}}`) |
| `measurement_window_turns` | `int` | Number of turns in the client-side analysis window |
| `baseline_sessions_remaining` | `int` | Sessions remaining before baseline locks |
| `baseline_samples` | `list[float]` | Collected baseline scores (cleared after lock) |
| `last_measured_utc` | `str \| None` | ISO 8601 timestamp of last measurement |
| `session_history` | `list[dict]` | Rolling history of `{complexity, delta, measured_utc}` entries |

---

## FUNCTIONS

### `vocabulary_growth_step(state, evidence, params) → tuple[dict, dict]`

Evaluates one vocabulary complexity measurement and returns updated state plus a decision dict.

**Parameters**

| Name | Type | Description |
|------|------|-------------|
| `state` | `dict` | The `vocabulary_tracking` section of the student's session state. Missing keys are filled with defaults |
| `evidence` | `dict` | Structured metrics from the client — must include `vocabulary_complexity_score` (float 0..1) |
| `params` | `dict \| None` | Optional parameter overrides (see Parameters) |

**Evidence fields:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `vocabulary_complexity_score` | `float` | Yes | Composite 0..1 score from client-side `vocabularyAnalyzer.ts` |
| `lexical_diversity` | `float` | No | Type-token ratio |
| `avg_word_length` | `float` | No | Average word length |
| `embedding_spread` | `float` | No | Cosine distance spread of student's vocabulary |
| `domain_terms_detected` | `list[str]` | No | Domain terms found; format `"module_id:term"` or `"term"` |
| `buffer_turns` | `int` | No | Number of turns analyzed by the client |
| `measurement_valid` | `bool` | No | Whether the client had enough data (default `True`) |

**Returns**

A `(state, decision)` tuple where `decision` contains:

| Key | Type | Description |
|-----|------|-------------|
| `vocab_growth_delta` | `float` | Growth above baseline (always ≥ 0) |
| `domain_terms_acquired` | `int` | Number of domain terms recorded this turn |
| `measurement_valid` | `bool` | `True` when the measurement met minimum criteria |
| `reward_weight_contribution` | `float` | Proportional reward signal for the reward system |

---

## PARAMETERS

Default values defined in `DEFAULT_PARAMS`; overridden per-domain from `runtime-config.yaml` under `runtime.domain_step_params.vocabulary_monitor`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `measurement_window_turns` | `20` | Number of turns in the client-side rolling analysis window |
| `min_turns_for_measurement` | `10` | Minimum turns required before a measurement is considered valid |
| `baseline_lock_sessions` | `3` | Number of sessions to collect before locking the baseline average |
| `session_history_max` | `50` | Maximum entries in the rolling session history |

---

## CLIENT-SIDE INTEGRATION

The vocabulary complexity score is computed entirely client-side by `src/web/services/vocabularyAnalyzer.ts`. The analyzer runs inside the React app and:

1. Buffers the student's messages in a rolling window
2. Computes lexical diversity (type-token ratio), average word length, and embedding spread
3. Detects domain-specific terms from the physics glossary
4. Produces a composite `vocabulary_complexity_score` (0..1)
5. Posts the structured metric to `POST /api/user/{user_id}/vocabulary-metric`

The API endpoint is a domain-declared route (see [`api-server-architecture(7)`](../../../../docs/7-concepts/api-server-architecture.md) §G), registered in the education domain's `cfg/runtime-config.yaml` under `adapters.api_routes`.

---

## SEE ALSO

- [`fluency-monitor(3)`](fluency-monitor.md) — Tier-advancement fluency gate (sibling domain-lib monitor)
- [`learning-profile(7)`](../../../../docs/7-concepts/learning-profile.md) — Student profile schema including `vocabulary_tracking`
- [`domain-pack-anatomy(7)`](../../../../docs/7-concepts/domain-pack-anatomy.md) — Eight-component domain pack structure
- `domain-packs/education/domain-lib/vocabulary_growth_monitor_v0_1.py` — Implementation
- `src/web/services/vocabularyAnalyzer.ts` — Client-side complexity analyzer
- `domain-packs/education/controllers/api_handlers.py` — Domain API route handlers
