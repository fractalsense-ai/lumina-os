"""Shim: canonical source at model-packs/system/domain-lib/sensors/hw_gpu.py"""
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l
_mod = _l("model-packs/system/domain-lib/sensors/hw_gpu.py")
get_gpu_usage = _mod.get_gpu_usage