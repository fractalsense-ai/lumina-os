# fluency-monitor(3)

## NAME

`fluency_monitor.py` — Consecutive-success fluency gate for tier advancement

## SYNOPSIS

```python
from fluency_monitor import FluencyState, fluency_monitor_step

state = FluencyState()
state, decision = fluency_monitor_step(state, task_spec, evidence, params)
```

## DESCRIPTION

`fluency_monitor.py` is an education domain-lib component that tracks whether a student has achieved **procedural fluency** on the current difficulty tier before advancing to a harder one. Advancement requires `target_consecutive_successes` correct solves each completed within `time_threshold_seconds`.

The fluency monitor runs as a **secondary** state monitor in `domain_step()` alongside the primary ZPD monitor. ZPD drift actions take priority; the fluency decision is merged in only when the ZPD monitor returns no action.

**Fluency decision outcomes:**

| Condition | Action |
|-----------|--------|
| `target_consecutive_successes` correct solves within time threshold | `advance_tier` |
| Correct solve but exceeded time threshold | `trigger_targeted_hint` (fluency bottleneck) |
| Incorrect or partial | `None` (reset streak) |
| Already at final tier + sufficient streak | `None` (no further advancement) |

This module conforms to the domain-state-lib contract: deterministic, structured I/O, no free text, same inputs → same outputs.

---

## DATA TYPES

### `FluencyState`

```python
@dataclass
class FluencyState:
    consecutive_correct: int = 0
    current_tier: str = "tier_1"
    solve_times: list[float] = field(default_factory=list)
```

| Field | Type | Description |
|-------|------|-------------|
| `consecutive_correct` | `int` | Number of consecutive correct solves within the time threshold in the current streak |
| `current_tier` | `str` | Active difficulty tier ID matching a `tier_progression` entry in runtime config |
| `solve_times` | `list[float]` | Recent `solve_elapsed_sec` values for the current streak (cleared on reset) |

---

## FUNCTIONS

### `fluency_monitor_step(state, task_spec, evidence, params) → tuple[FluencyState, dict]`

Evaluates one turn of evidence and returns updated state plus a decision dict.

**Parameters**

| Name | Type | Description |
|------|------|-------------|
| `state` | `FluencyState` | Current fluency state |
| `task_spec` | `dict` | Active task specification (accepted for interface consistency; not used internally) |
| `evidence` | `dict` | Structured turn evidence — must include `correctness` (str) and `solve_elapsed_sec` (float) |
| `params` | `dict \| None` | Optional parameter overrides (see Parameters) |

**Returns**

A `(FluencyState, decision)` tuple where `decision` contains:

| Key | Type | Description |
|-----|------|-------------|
| `action` | `str \| None` | `"advance_tier"`, `"trigger_targeted_hint"`, or `None` |
| `fluency_bottleneck` | `bool` | `True` when solve was correct but too slow |
| `consecutive_correct` | `int` | Updated streak count |
| `current_tier` | `str` | Active tier (may have changed if `advance_tier` was returned) |
| `advanced` | `bool` | `True` when tier was advanced this turn |
| `next_tier` | `str \| None` | New tier ID if `advanced` is `True` |

---

## PARAMETERS

Default values defined in `DEFAULT_PARAMS`; overridden per-domain from `runtime-config.yaml` under `runtime.domain_step_params.fluency_monitor`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `target_consecutive_successes` | `3` | Number of consecutive correct solves required to advance |
| `time_threshold_seconds` | `45.0` | Maximum seconds per solve to count toward the streak |
| `tier_progression` | `["tier_1", "tier_2", "tier_3"]` | Ordered list of tier IDs |

Runtime config example (education domain):

```yaml
domain_step_params:
  fluency_monitor:
    target_consecutive_successes: 3
    time_threshold_seconds: 45
    tier_progression:
      - tier_1
      - tier_2
      - tier_3
```

---

## SOURCE

`domain-packs/education/reference-implementations/fluency_monitor.py`

## SEE ALSO

- `domain-packs/education/reference-implementations/runtime-adapters.py` — calls `fluency_monitor_step` inside `domain_step()`; merges with ZPD decision
- `domain-packs/education/reference-implementations/problem_generator.py` — called when `advance_tier` is returned to produce a new harder problem
- `domain-packs/education/runtime-config.yaml` — `domain_step_params.fluency_monitor` configures thresholds
- `domain-packs/education/domain-lib/zpd-monitor-spec-v1.md` — ZPD monitor (primary state estimator; takes priority over fluency decisions)
