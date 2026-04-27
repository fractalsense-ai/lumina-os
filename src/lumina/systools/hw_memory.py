"""Shim: canonical source at model-packs/system/domain-lib/sensors/hw_memory.py"""
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l
_mod = _l("model-packs/system/domain-lib/sensors/hw_memory.py")
get_memory_usage = _mod.get_memory_usage