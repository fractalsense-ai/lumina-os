"""Shim: canonical source at model-packs/system/domain-lib/sensors/hw_loop_latency.py"""
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l
_mod = _l("model-packs/system/domain-lib/sensors/hw_loop_latency.py")
measure_loop_latency_async = _mod.measure_loop_latency_async
measure_loop_latency = _mod.measure_loop_latency