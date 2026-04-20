# Planning Task Specification — Assistant Domain
## version: 0.1.0

### Task Shape
Extended multi-turn. User describes a goal, system gathers constraints, generates a plan, iterates.

### Invariants
| ID | Severity | Description |
|---|---|---|
| `no_autonomous_execution` | warning | Plans must be presented for user approval. No autonomous execution. |
| `constraint_grounded` | warning | Plans must be grounded in user-provided constraints. |
| `content_safety_hard` | critical | Hard safety gate. |

### Standing Orders
| ID | Trigger | Description |
|---|---|---|
| `gather_constraints_first` | `constraint_grounded` | Ask about deadlines, resources, priorities before generating. |
| `request_execution_approval` | `no_autonomous_execution` | Present plan and ask for approval before execution steps. |
| `safety_intervene` | `content_safety_hard` | Escalate immediately. |

### Tool Adapters
- `adapter/asst/planning-tools/v1` — create, list, update, complete, delete operations for plan management.

### Task Lifecycle
1. User describes a goal or project
2. System gathers constraints (standing order: gather_constraints_first)
3. System generates plan via LLM + planning_create_tool
4. User reviews, approves, or requests changes
5. Iterate until plan is finalized → task completed
6. User may return later to update → planning_update_tool
