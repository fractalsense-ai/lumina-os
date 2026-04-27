# Agriculture Domain Library

Shared pure-function libraries and reference specifications for the agriculture domain pack.
These are **Group Libraries** — loaded once by the runtime and cached
across all modules that reference them via `group_libraries` pointers
in their domain-physics files.

## Structure

```
domain-lib/
├── sensors/                                       # Sensor libraries
│   └── environmental_sensors.py                   # Normalization, tolerance checking, batch aggregation
└── reference/                                     # Reference specifications (Tech Manuals)
    └── turn-interpretation-spec-v1.md             # Turn interpretation output schema
```

## Contents

| File                                  | Description                                              |
|---------------------------------------|----------------------------------------------------------|
| `sensors/environmental_sensors.py`    | Sensor normalization, tolerance checking, batch aggregation |
| `reference/turn-interpretation-spec-v1.md` | Turn interpretation output schema for classifying operator intent |
