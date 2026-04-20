# Search Task Specification — Assistant Domain
## version: 0.1.0

### Task Shape
One-shot to short multi-turn. User asks a factual question, system searches and presents results.

### Invariants
| ID | Severity | Description |
|---|---|---|
| `tool_result_grounded` | warning | All factual claims must come from search tool results. |
| `source_cited` | warning | Responses must include source attribution. |
| `content_safety_hard` | critical | Hard safety gate. |

### Standing Orders
| ID | Trigger | Description |
|---|---|---|
| `requery_search_tool` | `tool_result_grounded` | Re-call search if LLM fabricated results. |
| `cite_sources` | `source_cited` | Add source citations to the response. |
| `safety_intervene` | `content_safety_hard` | Escalate immediately. |

### Tool Adapters
- `adapter/asst/search-api/v1` — query + max_results → title, snippet, url, relevance.

### Task Lifecycle
1. User asks a factual question
2. System identifies search intent
3. Tool call → web_search_tool(query, max_results)
4. Present grounded, cited results → task completed
5. If user refines query → continued turn with new search
