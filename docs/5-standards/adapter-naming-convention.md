---
version: 1.0.0
last_updated: 2026-03-20
---

# Adapter Naming Convention

## Overview

The Adapter Indexer (`src/lumina/core/adapter_indexer.py`) automatically
discovers tool adapter YAML files by scanning standardized directory
structures within domain packs.  This document specifies the naming and
layout conventions the scanner expects.

## Directory Layout

```
domain-packs/<domain>/
  modules/<module-name>/
    tool-adapters/
      <adapter-name>-adapter-v<version>.yaml
  controllers/
    runtime_adapters.py
    tool_adapters.py
```

## Tool Adapter YAML Files

### Naming Pattern

```
*-adapter-v*.yaml
```

Examples:
- `calculator-adapter-v1.yaml`
- `collar-sensor-adapter-v1.yaml`
- `algebra-parser-adapter-v1.yaml`

Files that do not match this glob pattern are **ignored** by the scanner.

### Required Fields

Every adapter YAML file must contain at minimum:

| Field | Type | Description |
|---|---|---|
| `id` | string | Globally unique adapter identifier (e.g. `adapter/edu/calculator/v1`) |
| `domain_id` | string | The domain physics ID this adapter belongs to |
| `tool_name` | string | Human-readable adapter name |
| `version` | string | Semantic version |
| `call_types` | list[string] | Operations this adapter supports |
| `input_schema` | object | JSON Schema for input payloads |
| `output_schema` | object | JSON Schema for output payloads |

See `standards/tool-adapter-schema-v1.json` for the full JSON Schema.

### Optional Fields

| Field | Type | Description |
|---|---|---|
| `description` | string | Longer description of the adapter's purpose |
| `authorization` | object | Who may call, consent requirements, rate limits |
| `error_handling` | object | Failure strategy and fallback standing orders |

## Runtime Adapter Modules

The scanner discovers Python modules by exact name:

- `controllers/runtime_adapters.py` — Domain-specific state builder, domain step, and turn interpreter
- `controllers/tool_adapters.py` — Python implementations of tool adapter logic

These are keyed in the router index as `<domain>/runtime_adapters` and
`<domain>/tool_adapters`.

## Precedence

Explicit adapter declarations in `runtime-config.yaml` **always take
precedence** over auto-discovered entries.  The indexer provides a
supplementary discovery layer — it does not override manual configuration.

## Files

| File | Purpose |
|---|---|
| `src/lumina/core/adapter_indexer.py` | Scanner implementation |
| `src/lumina/core/runtime_loader.py` | Integration point (merges discovered adapters) |
| `standards/tool-adapter-schema-v1.json` | Canonical adapter schema |
