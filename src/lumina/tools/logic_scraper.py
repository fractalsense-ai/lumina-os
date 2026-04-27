"""Shim: canonical source at model-packs/system/controllers/logic_scraper.py"""
import sys
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l
_canonical = _l("model-packs/system/controllers/logic_scraper.py")
sys.modules[__name__] = _canonical