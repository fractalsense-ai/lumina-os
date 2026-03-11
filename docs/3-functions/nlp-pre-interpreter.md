# nlp-pre-interpreter(3)

## NAME

`nlp-pre-interpreter.py` — Deterministic NLP pre-interpreter for the education domain

## SYNOPSIS

```python
from nlp_pre_interpreter import nlp_preprocess

anchors = nlp_preprocess(input_text, task_context)
```

## DESCRIPTION

`nlp-pre-interpreter.py` runs lightweight pattern-based extractors on a student message **before** the LLM turn interpreter is called. It produces structured evidence anchors that are injected into the LLM prompt as grounding context, improving accuracy and consistency without replacing the LLM call.

The LLM **always** runs (required by the upcoming world-sim). NLP results are starting-point anchors — the LLM may confirm or override any NLP value based on contextual judgment. For algebraically provable fields (`step_count`, `equivalence_preserved`), the algebra parser remains the post-LLM authority.

**Pipeline position:**

```
Student message
  │
  ├─→ NLP Pre-Interpreter  (this module, deterministic, <1ms)
  │      └─→ _nlp_anchors appended to context_hint
  │
  ├─→ LLM Turn Interpreter  (receives anchors in prompt)
  │      └─→ full evidence JSON
  │
  └─→ Algebra Parser Override  (post-LLM, overwrites step_count etc.)
         └─→ final evidence dict
```

**Runtime wiring:** Registered in `runtime-config.yaml` as the `nlp_pre_interpreter` adapter. Loaded by `runtime_loader.py` into `nlp_pre_interpreter_fn` and passed to the domain turn interpreter via `lumina-api-server.py`. If `nlp_pre_interpreter` is absent from the config the pipeline degrades gracefully to LLM-only (backward compatible).

---

## FUNCTIONS

### `nlp_preprocess(input_text, task_context) → dict`

Main entry point. Runs all four extractors and returns a partial evidence dict with `_nlp_anchors` metadata.

**Parameters**

| Name | Type | Description |
|------|------|-------------|
| `input_text` | `str` | Raw student message |
| `task_context` | `dict` | Current task context; `task_context["current_problem"]["expected_answer"]` is used for answer matching |

**Returns**

A `dict` containing:

| Key | Type | Description |
|-----|------|-------------|
| `correctness` | `str \| absent` | `"correct"` or `"incorrect"` — only present when an answer was extracted and `expected_answer` is known |
| `frustration_marker_count` | `int` | Number of frustration signals detected (always present) |
| `hint_used` | `bool` | Whether a hint was requested (always present) |
| `off_task_ratio` | `float` | Fraction of tokens not classified as math vocabulary (always present) |
| `_nlp_anchors` | `list[dict]` | Metadata list for LLM prompt injection — see Anchor Format |

**Anchor Format**

Each entry in `_nlp_anchors`:

```json
{
  "field": "correctness",
  "value": "correct",
  "confidence": 0.95,
  "detail": "matched answer \"4\" to expected \"4\""
}
```

`detail` is optional; `confidence` is always present.

---

### `extract_answer_match(input_text, expected_answer) → dict`

Extracts a numeric answer from the student message and compares it to the expected answer.

**Patterns matched (in precedence order):**

1. `x = N` — variable assignment on a line by itself (multi-line aware)
2. `answer is N` / `equals N`
3. Bare number — message contains only a number

The last matched value (bottom of the message) is used as the student's answer.

**Returns**

| Key | Type | Description |
|-----|------|-------------|
| `correctness` | `str \| None` | `"correct"`, `"incorrect"`, or `None` (no answer found or no expected answer) |
| `confidence` | `float` | `0.95` for correct, `0.90` for incorrect, `0.0` for no match |
| `extracted_answer` | `float` | Present when a numeric answer was found |

---

### `extract_frustration_markers(input_text) → dict`

Detects frustration signals in a student message.

**Detection rules:**

| Signal | Rule |
|--------|------|
| Keyword phrases | "I don't get it", "I don't understand", "I can't", "I give up", "this is stupid", "this is hard", "this is impossible", "this makes no sense", "ugh", "argh" |
| ALL_CAPS | >50 % of alphabetic characters are uppercase, and there are ≥4 alpha chars |
| excessive_punctuation | 3 or more consecutive `!` or `?` |
| short_frustrated | Message <5 characters and contains `!` or `?` |

**Returns**

| Key | Type | Description |
|-----|------|-------------|
| `frustration_marker_count` | `int` | Total number of signals detected |
| `markers` | `list[str]` | List of matched signal identifiers / phrases |

---

### `extract_hint_request(input_text) → dict`

Detects whether the student is requesting a hint or help.

**Patterns matched:** "give me a hint", "hint please", "can I get a hint", "help me", "help", "I'm stuck", "I need help", "what do I do", "how do I"

**Returns**

| Key | Type |
|-----|------|
| `hint_used` | `bool` |

---

### `extract_off_task_ratio(input_text) → dict`

Estimates what fraction of a message is off-topic by checking token overlap with a fixed math vocabulary list.

**Math vocabulary:** numbers, operators (`+`, `-`, `*`, `/`, `=`, etc.), single-letter variables (a–z), and ~35 domain-specific terms (add, subtract, equation, solve, coefficient, substitution, …).

**Formula:** `off_task_ratio = 1.0 − (math_tokens / total_tokens)`, clamped to `[0.0, 1.0]`.

**Returns**

| Key | Type |
|-----|------|
| `off_task_ratio` | `float` |

---

## SOURCE

`domain-packs/education/reference-implementations/nlp-pre-interpreter.py`

## SEE ALSO

- `runtime-config.yaml` — adapter registration (`nlp_pre_interpreter` entry)
- `reference-implementations/runtime_loader.py` — loads `nlp_pre_interpreter_fn`
- `domain-packs/education/reference-implementations/runtime-adapters.py` — calls `nlp_preprocess` before the LLM, formats anchors into `context_hint`
- `domain-packs/education/prompts/turn-interpretation.md` — LLM prompt that acknowledges NLP anchors
- `tests/test_nlp_pre_interpreter.py` — 34 unit tests across all extractors
