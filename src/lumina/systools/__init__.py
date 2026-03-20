"""lumina.systools — System tools for Project Lumina.

Tools in this package fall into two categories with distinct calling conventions:

──────────────────────────────────────────────────────────────────────────────
CATEGORY 1 — ACTIVE ADMIN TOOLS  (policy-driven / CLI-invoked)
──────────────────────────────────────────────────────────────────────────────
Called by CLI entry points or by the orchestrator's policy system on specific
resolved actions.  These are the system-level analogue of domain tool-adapters.

  manifest_integrity.py   check / regen SHA-256 artifact manifest
  verify_repo.py          cross-check provenance hashes in System Log and schemas
  yaml_converter.py       compile YAML source files to JSON
  system_log_validator.py        validate System Log hash-chain integrity
  security_freeze.py      freeze / audit security-sensitive config state
  ppa_demo.py             deterministic PPA orchestrator demo runner (dev tool)

──────────────────────────────────────────────────────────────────────────────
CATEGORY 2 — PASSIVE HARDWARE PROBES  (lib-invoked only)
──────────────────────────────────────────────────────────────────────────────
Called BY src/lumina/lib/system_health.py (SystemHealthMonitor.sample()).
Never called directly by the core orchestrator or CLI entry points.
These are the system-level analogue of domain-lib passive state estimators.

  hw_disk.py    disk usage  (total, used, free, pct_used)
  hw_temp.py    CPU temperature  (platform-specific; gracefully absent)
  hw_memory.py  system memory  (total, used, free, available, pct_used)

Out-of-scope (not yet implemented):
  csv_exporter.py    export System Log records or session summaries as CSV
  graph_renderer.py  generate charts from System Logs aggregate data
"""

