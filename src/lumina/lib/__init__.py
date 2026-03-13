"""lumina.lib — Domain-library equivalent for the system domain.

The ``lib`` package holds passive state estimators that belong to
Lumina's system layer — the exact analogue of domain-lib components
in named domain packs (e.g., the education ZPD monitor or fluency
tracker).

Calling convention
------------------
Components here are called BY the **system runtime adapter** each
orchestration cycle to update mutable system state.  They are NEVER
called directly by the core orchestrator (``lumina.orchestrator``) or
by the CLI.

Current components
------------------
system_health.py
    Samples passive hardware probes (hw_disk, hw_temp, hw_memory)
    from ``lumina.systools`` and aggregates their values into a single
    ``SystemHealthState`` snapshot.
"""
