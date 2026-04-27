"""Shim: canonical source at model-packs/system/domain-lib/sensors/hw_http_queue.py"""
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l
_mod = _l("model-packs/system/domain-lib/sensors/hw_http_queue.py")
increment = _mod.increment
decrement = _mod.decrement
get_inflight_requests = _mod.get_inflight_requests
reset = _mod.reset