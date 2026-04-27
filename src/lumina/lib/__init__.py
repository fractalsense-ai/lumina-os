"""lumina.lib — Compatibility shims for system domain-lib.

Canonical source: model-packs/system/domain-lib/
Shim layer:       src/lumina/lib/

The real implementations have been relocated to the system domain pack
(model-packs/system/domain-lib/).  Each module in this package is a
thin shim that loads from the canonical location and re-exports its
public API so that existing ``from lumina.lib.system_health import …``
statements continue to work without modification.

See also: ``lumina.systools._domain_pack_loader``
"""
