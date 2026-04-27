# Weather Task Specification — Assistant Domain
## version: 0.1.0

### Task Shape
One-shot to short multi-turn. User asks about weather, system calls the tool, presents results.

### Invariants
| ID | Severity | Description |
|---|---|---|
| `tool_result_grounded` | warning | Responses must be grounded in tool output — no fabricated forecasts. |
| `location_resolved` | warning | Location must be resolved before calling the weather API. |
| `content_safety_hard` | critical | Hard safety gate. |

### Standing Orders
| ID | Trigger | Description |
|---|---|---|
| `requery_weather_tool` | `tool_result_grounded` | Re-call tool if LLM attempted to fabricate results. |
| `resolve_location` | `location_resolved` | Ask user to clarify location. |
| `safety_intervene` | `content_safety_hard` | Escalate immediately. |

### Tool Adapters
- `adapter/asst/weather-api/v1` — Location + forecast_days → temperature, conditions, humidity, wind, forecast array.

### Task Lifecycle
1. User asks a weather question
2. NLP pre-interpreter extracts location hint (if present)
3. If location missing → standing order: resolve_location
4. Tool call → weather_lookup_tool(location, forecast_days)
5. Present grounded result → task completed
