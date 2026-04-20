# Calendar Task Specification — Assistant Domain
## version: 0.1.0

### Task Shape
Short multi-turn. User queries or modifies calendar events. Write operations require confirmation.

### Invariants
| ID | Severity | Description |
|---|---|---|
| `no_unauthorized_modification` | warning | Write ops must be confirmed by user before execution. |
| `date_range_bounded` | warning | Queries must have a bounded date range. Defaults to current week. |
| `content_safety_hard` | critical | Hard safety gate. |

### Standing Orders
| ID | Trigger | Description |
|---|---|---|
| `confirm_before_write` | `no_unauthorized_modification` | Ask user to confirm before CUD operations. |
| `request_date_range` | `date_range_bounded` | Ask user for date range, or default to current week. |
| `safety_intervene` | `content_safety_hard` | Escalate immediately. |

### Tool Adapters
- `adapter/asst/calendar-api/v1` — action (query/create/update/delete), date_start, date_end, event_title, event_id.

### Task Lifecycle
1. User asks about calendar / requests event modification
2. NLP pre-interpreter extracts date hints
3. If date range missing → standing order: request_date_range
4. Query → calendar_query_tool; Write → calendar_write_tool (after confirmation)
5. Present result → task completed (or continued if user has follow-ups)
