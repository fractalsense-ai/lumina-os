"""Shim: canonical source at model-packs/system/controllers/security_freeze.py"""
import sys
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l
_canonical = _l("model-packs/system/controllers/security_freeze.py")
sys.modules[__name__] = _canonical