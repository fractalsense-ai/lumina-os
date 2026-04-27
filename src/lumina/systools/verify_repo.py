"""Shim: canonical source at model-packs/system/controllers/verify_repo.py

This shim replaces itself in sys.modules with the canonical module so that
``patch.object(verify_mod, "REPO_ROOT", ...)`` in tests modifies the actual
module globals used by the original functions.
"""
import sys
from lumina.systools._domain_pack_loader import load_domain_pack_module as _l

_canonical = _l("model-packs/system/controllers/verify_repo.py")
sys.modules[__name__] = _canonical