"""Education domain turn-0 presenter hook.

Extracts the turn-0 equation presentation logic from the system pipeline.
When a student enters a learning module for the first time, present the
generated equation before evaluating their input.

Called by processing.py via the ``turn_0_presenter_fn`` hook point.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

log = logging.getLogger("lumina.education.turn0")


def education_turn0_check(
    *,
    session: dict[str, Any],
    current_task: dict[str, Any],
    holodeck: bool,
    deterministic_response: bool,
) -> bool:
    """Return True if this turn qualifies for turn-0 equation presentation."""
    _turn_count = session.get("turn_count", 0)
    _has_equation = isinstance(current_task, dict) and bool(current_task.get("equation"))
    return _turn_count == 0 and _has_equation and not holodeck and not deterministic_response
