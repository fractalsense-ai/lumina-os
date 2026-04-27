"""lumina.systools - Compatibility shims for system domain pack.

Canonical source: model-packs/system/
Shim layer:       src/lumina/systools/

The real implementations have been relocated to the system domain pack
(model-packs/system/controllers/ for active tools, model-packs/system/
domain-lib/sensors/ for passive probes).  Each module in this package
is a thin shim that loads from the canonical location and re-exports
its public API so that existing ``from lumina.systools.X import Y``
statements continue to work without modification.

See also: ``lumina.systools._domain_pack_loader``
"""