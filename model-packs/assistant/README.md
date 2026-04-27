# Assistant Domain Pack

A **general-purpose conversational assistant** domain for Project Lumina.

Users interact through free-form chat. Each turn is classified by intent and
routed to the appropriate task module. The conversation commons aggregates
tools from all sibling modules and serves as the default landing zone.

---

## Design Principles

- **Intent-based per-turn routing** — every turn is classified (weather,
  calendar, search, creative-writing, planning, general) and the active
  module shifts to match. No assignment-based routing.
- **Commons aggregates tools** — the `conversation/` module has access to
  every user-module tool. Specialized modules add governance (invariants,
  standing orders, state tracking).
- **Safety-only user escalation** — only hard safety invariants
  (`content_safety_hard`) trigger escalation. Task failures do not escalate;
  they are tracked as positive invariants.
- **Task tracking as positive invariants** — each task type module tracks
  task lifecycle (open → completed | abandoned | deferred).
- **Module-per-task-type** — fault isolation and traceability. If a
  hallucination occurs inside `weather/`, the diagnostic boundary is clear.

---

## Directory Structure

```
assistant/
├── pack.yaml                          # Pack identity & HMVC layer map
├── CHANGELOG.md                       # Version history
├── README.md                          # This file
├── cfg/
│   ├── runtime-config.yaml            # Runtime configuration
│   ├── ui-config.yaml                 # UI manifest and role layouts
│   ├── admin-operations.yaml          # Slash-command operations
│   └── domain-profile-extension.yaml  # Domain-wide profile fields (Layer 2)
├── controllers/
│   ├── runtime_adapters.py            # 3 required callables
│   ├── nlp_pre_interpreter.py         # Intent classification
│   ├── tool_adapters.py               # Stub tool implementations
│   ├── assistant_operations.py        # Ops dispatcher (slash commands)
│   └── assistant_escalation_context.py # Escalation hook
├── domain-lib/
│   ├── task_tracker.py                # Task lifecycle state machine
│   └── reference/
│       ├── turn-interpretation-spec-v1.md
│       ├── weather-task-spec-v1.md
│       ├── calendar-task-spec-v1.md
│       ├── search-task-spec-v1.md
│       ├── creative-writing-task-spec-v1.md
│       └── planning-task-spec-v1.md
├── modules/
│   ├── conversation/                  # Commons — free-form chat landing zone
│   ├── weather/                       # Weather lookup
│   ├── calendar/                      # Calendar management
│   ├── search/                        # Web search
│   ├── creative-writing/              # Creative writing (no tools)
│   ├── planning/                      # Planning & task management
│   └── domain-authority/              # Governance
├── profiles/
│   └── entity.yaml                    # Default entity profile (Layer 3)
├── prompts/
│   └── domain-persona-v1.md           # LLM persona prompt
└── web/
    └── plugin.ts                      # Frontend plugin
```

---

## Module Routing

| Intent Class     | Module              | Tools | Turn Shape        |
|-----------------|---------------------|-------|-------------------|
| `general`       | conversation/       | all   | Free-form         |
| `weather`       | weather/            | weather-api | One-shot    |
| `calendar`      | calendar/           | calendar-api | Short multi-turn |
| `search`        | search/             | search-api | One-shot → short |
| `creative`      | creative-writing/   | none  | Iterative         |
| `planning`      | planning/           | planning-tools | Extended  |
| `governance`    | domain-authority/   | DA tools | Multi-turn     |

---

## Further Reading

- [Authoring a Domain Pack](../../docs/7-concepts/authoring-a-domain-pack.md)
- [Domain Adapter Pattern](../../docs/7-concepts/domain-adapter-pattern.md)
- [HMVC Heritage](../../docs/7-concepts/hmvc-heritage.md)
