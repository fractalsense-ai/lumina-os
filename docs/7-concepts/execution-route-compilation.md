---
version: 1.0.0
last_updated: 2026-03-27
---

# Concept — Execution Route Compilation

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-27  

---

## NAME

execution-route-compilation — ahead-of-time compilation of domain-physics
execution routes into flat lookup tables

## SYNOPSIS

The **route compiler** transforms declarative domain-physics pointers —
invariant → standing-order → tool-adapter → group-library references —
into pre-resolved flat lookup tables at startup.  The orchestrator and
middleware then execute O(1) dictionary lookups per turn instead of
walking the reference graph at runtime.

This is the Lumina equivalent of a **shader cache**: a compile-once,
lookup-many optimisation that converts a human-authored declaration graph
into a machine-optimised execution surface.

---

## DESCRIPTION

### A. The Semantic Compiler Concept

Lumina's core engine functions as a **semantic compiler** — an ahead-of-time
(AOT) compilation engine for natural language processing pipelines.  Four
compilation phases prepare a domain pack's raw specifications into runtime-ready
data structures:

| Phase | Analogy | Subsystem | Output |
|-------|---------|-----------|--------|
| Lexical Ingestion | Tokenisation | Retrieval embedder + housekeeper | Per-domain `.npz` vector stores |
| Dependency Linking | Linking shared libraries | Adapter indexer + Group Libraries | `RouterIndex` with group_libraries and group_tools |
| Semantic Logic Graphing | Building the AST | Physics file parser + invariant registry | Invariant/standing-order/escalation declaration graph |
| **AOT Caching** | **Shader compilation** | **Route compiler** | **`CompiledRoutes` flat lookup tables** |

The route compiler is Phase 4 — the final compilation step that produces the
execution-ready artefact.  Once `CompiledRoutes` is built, no further graph
resolution is needed during turn processing.

### B. What Gets Compiled

Three frozen dataclasses form the compiled output:

#### InvariantRoute

Pre-resolved route for a single invariant violation.  When the orchestrator's
`invariant_checker` detects a violation, it looks up the invariant ID in the
compiled table and immediately obtains the standing order, tool adapter, and
library dependencies — no graph walk required.

```python
@dataclass(frozen=True)
class InvariantRoute:
    invariant_id: str
    standing_order_id: str
    tool_adapter_id: str | None = None
    library_deps: tuple[str, ...] = ()
```

#### StandingOrderRoute

Pre-resolved tool chain for a single standing order.  When the `ActorResolver`
matches a resolved action to a standing order, it reads the tool chain directly
from the compiled table.

```python
@dataclass(frozen=True)
class StandingOrderRoute:
    standing_order_id: str
    tool_chain: tuple[str, ...] = ()
    library_deps: tuple[str, ...] = ()
```

#### CompiledRoutes

The top-level container exposing O(1) lookup methods, introspection
properties, and dependency aggregation.

```python
@dataclass
class CompiledRoutes:
    _invariant_routes: dict[str, InvariantRoute]
    _standing_order_routes: dict[str, StandingOrderRoute]
    domain_id: str = ""

    def invariant_route(self, invariant_id: str) -> InvariantRoute | None: ...
    def standing_order_tools(self, so_id: str) -> StandingOrderRoute | None: ...
    def all_library_deps(self) -> set[str]: ...
    def all_tool_ids(self) -> set[str]: ...
    def has_routes(self) -> bool: ...
```

All three dataclasses are frozen (or effectively immutable) after compilation.
The orchestrator reads from them; it never writes.

### C. Compilation Pipeline

`compile_execution_routes()` is the single entry point.  It accepts a parsed
domain-physics dict and optional validation indexes:

```python
compiled = compile_execution_routes(
    domain_physics,
    tool_index=available_tools,
    library_index=available_libraries,
    strict=False,
)
```

The compiler follows a four-step procedure:

**Step 1 — Extract declarations.**  Parse `invariants`, `standing_orders`, and
`execution_policy.precompiled_routes` from the physics dict.

**Step 2 — Compile invariant handlers.**  For each entry in
`precompiled_routes.invariant_handlers`, validate that:
- The invariant ID exists in the physics invariants.
- The referenced standing order exists.
- The tool adapter ID (if any) exists in the tool index.
- All library dependencies exist in the library index.

If validation passes, an `InvariantRoute` is emitted.

**Step 3 — Compile standing-order tool chains.**  For each entry in
`precompiled_routes.standing_order_tools`, validate standing order existence,
tool chain entries, and library dependencies.  Emit a `StandingOrderRoute`.

**Step 4 — Auto-compile fallback.**  If no `precompiled_routes` section exists
in the physics file, the compiler walks the invariant list and builds routes
automatically from `standing_order_on_violation` references.  This means
existing physics files compile without any schema additions — the explicit
section is an optimisation, not a requirement.

#### Strict vs non-strict mode

| Mode | Missing reference behaviour |
|------|----------------------------|
| `strict=True` (default) | Raises `RouteCompilationError` — fail-fast during testing and CI |
| `strict=False` | Logs a warning and skips the invalid route — used at startup to avoid blocking the server |

### D. The Deterministic Gate

The compiled routes slot into the D.S.A. orchestrator's **deterministic gate**
— the invariant checker + ActorResolver pipeline that processes every turn
before the LLM response is finalised.

```
Turn evidence
     │
     ▼
┌────────────────────────┐
│ Invariant Checker       │  For each invariant violation:
│                         │    route = compiled.invariant_route(inv_id)
│                         │    → standing_order_id, tool, library_deps
└───────────┬─────────────┘
            │
            ▼
┌────────────────────────┐
│ ActorResolver           │  For each resolved action:
│                         │    chain = compiled.standing_order_tools(so_id)
│                         │    → tool_chain, library_deps indexed in O(1)
│                         │  Exposes last_tool_chain for telemetry
└───────────┬─────────────┘
            │
            ▼
     Turn response
```

The `ActorResolver` builds an internal `_so_index` (a `dict[str, int]`) at
construction time, mapping standing-order IDs to their position in the
standing-orders list.  Combined with `CompiledRoutes`, every resolution step
is a dictionary lookup.

#### Integration in PPAOrchestrator

The `PPAOrchestrator` accepts `compiled_routes` at construction and forwards
the reference to `ActorResolver`.  No copying occurs — both components share
the same immutable `CompiledRoutes` instance.

### E. Integration Points

| Subsystem | Role |
|-----------|------|
| `runtime_loader.py` | Calls `compile_execution_routes()` after tool/library discovery; stores result in `ctx["compiled_routes"]` |
| `ppa_orchestrator.py` | Receives `compiled_routes` parameter; passes to `ActorResolver` |
| `actor_resolver.py` | Uses `compiled_routes` for O(1) lookups; exposes `last_tool_chain` |
| `adapter_indexer.py` | Provides `tool_index` and `library_index` for compile-time validation |
| Domain-physics JSON | Declares `execution_policy.precompiled_routes` (optional) |

---

## SCHEMA

The `precompiled_routes` object is declared inside `execution_policy` in the
domain-physics schema (`standards/domain-physics-schema-v1.json`):

```json
{
  "execution_policy": {
    "precompiled_routes": {
      "invariant_handlers": {
        "<invariant_id>": {
          "standing_order_id": "<standing_order_id>",
          "tool_adapter_id": "<tool_id>",
          "library_deps": ["<library_id>"]
        }
      },
      "standing_order_tools": {
        "<standing_order_id>": {
          "tool_chain": ["<tool_id_1>", "<tool_id_2>"],
          "library_deps": ["<library_id>"]
        }
      }
    }
  }
}
```

All fields inside `invariant_handlers` and `standing_order_tools` are
optional — the compiler fills in defaults and auto-resolves where possible.

---

## SOURCE FILES

- `src/lumina/core/route_compiler.py` — `compile_execution_routes()`, `InvariantRoute`, `StandingOrderRoute`, `CompiledRoutes`, `RouteCompilationError`
- `src/lumina/core/runtime_loader.py` — route compilation block (invokes compiler after tool/library discovery)
- `src/lumina/orchestrator/actor_resolver.py` — `ActorResolver` with `_so_index` and `compiled_routes` support
- `src/lumina/orchestrator/ppa_orchestrator.py` — `PPAOrchestrator` forwards `compiled_routes` to `ActorResolver`
- `src/lumina/core/adapter_indexer.py` — `RouterIndex`, `GroupLibraryEntry`, `GroupToolEntry` (provide validation indexes)
- `standards/domain-physics-schema-v1.json` — schema for `execution_policy.precompiled_routes`
- `model-packs/agriculture/modules/operations-level-1/domain-physics.json` — reference implementation with precompiled routes

---

## SEE ALSO

- [`domain-pack-anatomy(7)`](domain-pack-anatomy.md) — physics-as-standing-orders design and the six-component anatomy
- [`group-libraries-and-tools(7)`](group-libraries-and-tools.md) — Group Libraries referenced in `library_deps`
- [`edge-vectorization(7)`](edge-vectorization.md) — vector stores built from the same adapter-indexer discovery pass
- [`domain-adapter-pattern(7)`](domain-adapter-pattern.md) — three-layer distinction and Phase A/B lifecycle
- [`resource-monitor-daemon(7)`](resource-monitor-daemon.md) — daemon-driven rebuilds that may trigger recompilation
