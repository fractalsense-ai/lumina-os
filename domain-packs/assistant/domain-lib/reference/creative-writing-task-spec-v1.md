# Creative Writing Task Specification — Assistant Domain
## version: 0.1.0

### Task Shape
Iterative multi-turn. User requests creative content, provides feedback, iterates.

### Invariants
| ID | Severity | Description |
|---|---|---|
| `content_safety_hard` | critical | Hard safety gate. Only invariant for creative writing — no style filters. |

### Standing Orders
| ID | Trigger | Description |
|---|---|---|
| `safety_intervene` | `content_safety_hard` | Escalate immediately. |
| `respect_creative_intent` | always | Match user's requested tone/style/format. Do not impose own preferences. |

### Tool Adapters
None. Pure LLM module — all output is generated, not tool-retrieved.

### Task Lifecycle
1. User requests creative content (story, poem, brainstorm, rephrase, etc.)
2. System identifies creative intent, captures genre/style hints
3. LLM generates content per user brief
4. User may iterate (revise, expand, change tone) → continued turns
5. User satisfied or moves on → task completed/abandoned
