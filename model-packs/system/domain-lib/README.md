# System Domain Library (`domain-lib/`)

Passive state estimators, reference specifications, and shared libraries for the **system** domain pack.

## Structure

```
domain-lib/
├── system_health.py                              # Aggregates sensor results into SystemHealthState
├── sensors/                                       # Hardware sensor probes
│   ├── hw_disk.py                                 # Disk usage (stub — needs psutil)
│   ├── hw_memory.py                               # Memory usage (stub — needs psutil)
│   ├── hw_temp.py                                 # CPU temperature (stub — platform-specific)
│   ├── hw_gpu.py                                  # GPU VRAM utilisation (stub — needs pynvml)
│   ├── hw_loop_latency.py                         # Asyncio event-loop latency
│   └── hw_http_queue.py                           # In-flight HTTP request counter
└── reference/                                     # Reference specifications (Tech Manuals)
    ├── turn-interpretation-spec-v1.md             # Turn interpretation output schema
    └── command-interpreter-spec-v1.md             # Admin command disambiguation rules
```

## Reference Specifications

The `reference/` subdirectory contains **Tech Manuals** — the interpretation
schemas and command rules that physics files (SOPs) reference. These define
_what to know_, not _how to talk_. Persona directives remain in `prompts/`.

## Calling Convention

Sensors and `system_health.py` are called by the **system runtime adapter**
each orchestration cycle.  They are **never** called directly by the core
orchestrator.

Compatibility shims at `src/lumina/systools/` and `src/lumina/lib/`
re-export these APIs so existing imports continue to work.