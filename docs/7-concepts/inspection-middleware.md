---
version: 1.0.0
last_updated: 2026-03-20
---

# Inspection Middleware

> Tier 2 of the Three-Tier Execution Pipeline  
> Module: `src/lumina/middleware/`  
> Schema: `standards/inspection-result-schema-v1.json`

## Overview

The Inspection Middleware is the deterministic boundary between LLM output
and execution.  Every payload the LLM generates must pass through this
pipeline **before** tool adapters or the orchestrator act on it.

```
Ingestion (sensors / domain library)
    → Inspection (middleware)        ← this module
        → Execution (actuators / tool adapters)
```

The middleware does **not** call any language model.  It evaluates
pre-authored domain-physics rules, schema declarations, and lightweight
NLP extractors using only deterministic Python stdlib operations.

## Pipeline Stages

### Stage 1 — NLP Pre-Processing

Runs domain-supplied extractor functions against the raw user input
**before** the LLM has seen it.  Extractors are composable callables of
type `NLPExtractorFn(input_text, task_context) → list[NLPAnchor]`.

Extracted anchors are merged into the payload using **LLM-precedence**
semantics: if the LLM already set a field, the NLP anchor is stored but
does not overwrite it.

Provided primitives: `keyword_match()`, `regex_extract()`,
`vocab_overlap_ratio()`, `caps_ratio()`, `punctuation_density()`.

### Stage 2 — Schema Validation

Validates the structured payload against the `turn_input_schema` declared
in the domain's `runtime-config.yaml`.  Checks:

| Check      | Blocks in strict mode? |
|------------|----------------------|
| Required fields missing | Yes |
| Type mismatch | Yes |
| Enum violation | No (warning) |
| Numeric out-of-bounds | No (warning) |

After validation, missing optional fields are filled from schema-declared
defaults via `sanitize_output()`.

### Stage 3 — Invariant Checking

Evaluates the domain-physics `invariants` list against the payload.  Each
invariant is a declarative rule with a `check` expression, e.g.:

```yaml
- id: "mastery_range"
  check: "mastery_estimate >= 0.0"
  severity: critical
```

Supported operators: `>=`, `<=`, `>`, `<`, `==`, `!=`, and truthy checks.

- **Critical** invariant failure → pipeline **denies** execution.
- **Warning** / **info** failures → recorded in violations, execution
  proceeds.

### Verdict

The pipeline returns an `InspectionResult`:

```python
@dataclass(frozen=True)
class InspectionResult:
    approved: bool
    violations: list[str]
    sanitized_payload: dict[str, Any]
    invariant_results: list[dict[str, Any]]
    nlp_result: NLPPreprocessResult | None
```

`approved = False` when:
- Any **critical** invariant fails, or
- Any **required-field** or **type-mismatch** violation occurs in strict mode.

The `to_dict()` method serialises the result for System Log audit metadata.

## Integration Point

The pipeline is invoked in `src/lumina/api/processing.py` inside
`process_message()`, immediately after `turn_data` is fully constructed
and normalised, and before `orch.process_turn()`:

```
construct turn_data
    ↓
normalize_turn_data()
    ↓
SLM physics interpretation (optional)
    ↓
InspectionPipeline.run()  ← gate
    ↓
orch.process_turn()       ← only if approved
```

When the pipeline denies execution, `process_message()` returns an
`inspection_denied` action with the full violation list, and the
orchestrator is never invoked.

## Strict vs. Permissive Mode

| Setting | Behaviour |
|---------|-----------|
| `strict=True` (default) | Schema violations cause denial |
| `strict=False` | Schema violations are warnings only |

The `local_only` runtime flag maps to `strict=False`, allowing graceful
degradation for system-domain turns that may not have a full
`turn_input_schema`.

## Files

| File | Purpose |
|------|---------|
| `src/lumina/middleware/__init__.py` | Package exports |
| `src/lumina/middleware/pipeline.py` | `InspectionPipeline`, `InspectionResult` |
| `src/lumina/middleware/invariant_checker.py` | `evaluate_check_expr()`, `evaluate_invariants()` |
| `src/lumina/middleware/output_validator.py` | `validate_output()`, `sanitize_output()` |
| `src/lumina/middleware/nlp_preprocessor.py` | NLP extraction primitives and `run_extractors()` |
| `standards/inspection-result-schema-v1.json` | JSON Schema for `InspectionResult.to_dict()` |

## Relation to Existing Modules

- **PPA Orchestrator** (`src/lumina/orchestrator/ppa_orchestrator.py`) —
  Previously owned invariant-checking inline.  Now imports
  `evaluate_invariants()` from the middleware for its internal
  `_evaluate_invariants` method.  Backward-compatible aliases are
  maintained.

- **API Auth Middleware** (`src/lumina/api/middleware.py`) — Handles JWT
  verification and RBAC.  This is a separate concern; the inspection
  middleware deals with *domain physics* validation, not authentication.

- **Domain Runtime Adapters** — Phase A NLP extractors in each domain
  pack's `runtime_adapters.py` can be composed into the pipeline's
  extractor list.
