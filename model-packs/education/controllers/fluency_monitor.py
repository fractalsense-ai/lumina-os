# Shim - canonical location: model-packs/education/domain-lib/fluency_monitor.py
# This file re-exports the canonical module so existing imports continue to work.
import importlib.util, sys
from pathlib import Path
_LIB = Path(__file__).resolve().parent.parent / "domain-lib" / "fluency_monitor.py"
_spec = importlib.util.spec_from_file_location("fluency_monitor_canonical", str(_LIB))
_mod = importlib.util.module_from_spec(_spec)
sys.modules["fluency_monitor_canonical"] = _mod
_spec.loader.exec_module(_mod)
sys.modules[__name__] = _mod