"""Education domain profile serializer hook.

Extracts education-specific profile persistence from the system pipeline:
- Fluency state extraction (current_tier, consecutive_correct)
- learning_state serialization from dataclass state
- Module-keyed two-tier state model
- SVA affect baseline tracking (floating EMA + per-module signatures)

Called by processing.py via the ``profile_serializer_fn`` hook point.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("lumina.education.profile-serializer")

# ── SVA Baseline EMA ─────────────────────────────────────────
_SVA_ALPHA = 0.1  # Smoothing factor for exponential moving average


def _load_assistant_affect_monitor():
    module_key = "lumina_model_packs_assistant_affect_monitor"
    cached = sys.modules.get(module_key)
    if cached is not None:
        return cached
    module_path = (
        Path(__file__).resolve().parents[2]
        / "assistant"
        / "domain-lib"
        / "affect_monitor.py"
    )
    spec = importlib.util.spec_from_file_location(module_key, module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Cannot load assistant affect monitor from {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = mod
    spec.loader.exec_module(mod)
    return mod


def _update_affect_baseline(
    profile_data: dict[str, Any],
    module_key: str | None,
    affect: dict[str, float],
) -> None:
    """Update the domain-wide SVA affect baseline on the profile.

    Uses an exponential moving average (EMA) so the baseline floats
    with the learner over time rather than locking after N samples.
    Also records a per-module affect signature with delta_from_baseline
    so teachers can see "this student's baseline SVA is X, but in
    algebra-1 their valence drops to Y".
    """
    ls = profile_data.get("learning_state")
    if not isinstance(ls, dict):
        return

    baseline = ls.get("affect_baseline")
    if not isinstance(baseline, dict):
        # Initialise baseline from first reading
        baseline = {
            "salience": affect.get("salience", 0.5),
            "valence": affect.get("valence", 0.0),
            "arousal": affect.get("arousal", 0.5),
            "sample_count": 1,
            "per_module": {},
        }
        ls["affect_baseline"] = baseline
        return

    alpha = _SVA_ALPHA
    old_s = float(baseline.get("salience", 0.5))
    old_v = float(baseline.get("valence", 0.0))
    old_a = float(baseline.get("arousal", 0.5))

    cur_s = float(affect.get("salience", old_s))
    cur_v = float(affect.get("valence", old_v))
    cur_a = float(affect.get("arousal", old_a))

    # EMA update
    baseline["salience"] = round(alpha * cur_s + (1 - alpha) * old_s, 6)
    baseline["valence"] = round(alpha * cur_v + (1 - alpha) * old_v, 6)
    baseline["arousal"] = round(alpha * cur_a + (1 - alpha) * old_a, 6)
    baseline["sample_count"] = int(baseline.get("sample_count", 0)) + 1

    # Per-module affect signature with delta from baseline
    if module_key:
        per_module = baseline.get("per_module")
        if not isinstance(per_module, dict):
            per_module = {}
            baseline["per_module"] = per_module
        per_module[module_key] = {
            "salience": cur_s,
            "valence": cur_v,
            "arousal": cur_a,
            "delta_from_baseline": {
                "salience": round(cur_s - baseline["salience"], 6),
                "valence": round(cur_v - baseline["valence"], 6),
                "arousal": round(cur_a - baseline["arousal"], 6),
            },
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }


def _extract_affect(orch_state: Any) -> dict[str, float] | None:
    """Extract the affect dict from either a dataclass or dict state."""
    if dataclasses.is_dataclass(orch_state):
        _affect = getattr(orch_state, "affect", None)
        if _affect is not None:
            if dataclasses.is_dataclass(_affect):
                return dataclasses.asdict(_affect)
            if isinstance(_affect, dict):
                return dict(_affect)
    elif isinstance(orch_state, dict):
        _affect = orch_state.get("affect")
        if isinstance(_affect, dict):
            return dict(_affect)
    return None


def education_serialize_profile(
    *,
    orch_state: Any,
    profile_data: dict[str, Any],
    module_key: str | None,
    persistence: Any | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Serialize education-specific orchestrator state into the profile dict.

    Handles both dataclass-based state (learning modules with fluency)
    and plain-dict state (governance/freeform modules).

    When *persistence* and *user_id* are provided, module state is written to
    the database instead of embedding it in the profile YAML.

    Also updates the domain-wide SVA affect baseline on the profile using
    an exponential moving average of per-turn affect readings.

    Returns the mutated profile_data dict.
    """
    # ── Update domain-wide SVA affect baseline ────────────────
    _affect = _extract_affect(orch_state)
    if _affect:
        _update_affect_baseline(profile_data, module_key, _affect)

    if dataclasses.is_dataclass(orch_state):
        _ls_dict = dataclasses.asdict(orch_state)
        if hasattr(orch_state, "fluency"):
            _ls_dict["fluency"] = {
                "current_tier": orch_state.fluency.current_tier,
                "consecutive_correct": orch_state.fluency.consecutive_correct,
            }
        # Persist module state to DB when available; otherwise fall back to YAML.
        if persistence is not None and user_id and module_key:
            persistence.save_module_state(user_id, module_key, _ls_dict)
        elif module_key:
            if not isinstance(profile_data.get("modules"), dict):
                profile_data["modules"] = {}
            profile_data["modules"][module_key] = _ls_dict
    else:
        _sd = orch_state if isinstance(orch_state, dict) else {}
        _state_snapshot = dict(_sd)

        # ── Relational baseline update ─────────────────────────
        # When the freeform/journal domain step places entity_mentions in
        # orch_state, update the per-entity EWMA baseline on the profile.
        # Entity names are never present here — only opaque hashes.
        _entity_mentions = _sd.get("entity_mentions")
        if _entity_mentions:
            _global_bl_data = (profile_data.get("learning_state") or {}).get("affect_baseline") or {}
            _affect_monitor = _load_assistant_affect_monitor()
            AffectBaseline = _affect_monitor.AffectBaseline
            update_relational_baseline = _affect_monitor.update_relational_baseline
            _global_bl = AffectBaseline.from_dict(_global_bl_data)
            _rel_bl = dict(
                (profile_data.get("learning_state") or {}).get("relational_baseline") or {}
            )
            for _hash, _signals in _entity_mentions.items():
                _rel_bl = update_relational_baseline(
                    _rel_bl,
                    _hash,
                    float(_signals.get("valence_delta", 0.0)),
                    float(_signals.get("arousal_delta", 0.0)),
                    float(_signals.get("salience_delta", 0.0)),
                    global_baseline=_global_bl,
                )
            _ls = profile_data.setdefault("learning_state", {})
            _ls["relational_baseline"] = _rel_bl

        profile_data["session_state"] = {
            "turn_count": int(_sd.get("turn_count", 0)),
            "operator_id": str(_sd.get("operator_id", "")),
        }
        # Persist module state to DB when available; otherwise fall back to YAML.
        if persistence is not None and user_id and module_key:
            persistence.save_module_state(user_id, module_key, _state_snapshot)
        elif module_key:
            if not isinstance(profile_data.get("modules"), dict):
                profile_data["modules"] = {}
            profile_data["modules"][module_key] = _state_snapshot

    return profile_data
