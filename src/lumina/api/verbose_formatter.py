"""Colored log formatter for verbose turn pipeline output.

Activated when ``LUMINA_VERBOSE=1`` (env-var) or ``--verbose`` (CLI flag).
Each pipeline stage gets a distinct ANSI color so operators can visually
parse the turn lifecycle in the terminal.
"""

from __future__ import annotations

import logging
import os

# ── ANSI colour codes ────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_RED = "\033[31m"
_WHITE = "\033[37m"

# Stage tag → colour mapping
_STAGE_COLORS: dict[str, str] = {
    "GATE": _CYAN,
    "INTERCEPT": _CYAN,
    "TURN": _YELLOW,
    "ENRICH": _GREEN,
    "INSPECT": _GREEN,
    "ORCH": _MAGENTA,
    "POST": _MAGENTA,
    "RESPONSE": _BLUE,
    "LLM": _BLUE,
    "SYNC": _DIM + _WHITE,
    "SEAL": _DIM + _WHITE,
    "PROV": _DIM + _WHITE,
    "RESULT": _BOLD + _WHITE,
    "ERROR": _RED,
    "WARN": _RED,
}


def _colorize(tag: str, message: str) -> str:
    color = _STAGE_COLORS.get(tag, _WHITE)
    return f"{color}{_BOLD}[{tag}]{_RESET} {color}{message}{_RESET}"


class ColoredTurnFormatter(logging.Formatter):
    """Drop-in ``logging.Formatter`` that colours ``[STAGE]`` prefixed messages.

    Non-stage messages pass through with the standard format.
    """

    def __init__(self, fmt: str | None = None, datefmt: str | None = None) -> None:
        super().__init__(
            fmt=fmt or "%(asctime)s %(message)s",
            datefmt=datefmt,
        )

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        msg = record.getMessage()
        # Detect [STAGE] prefix and apply colour
        if msg.startswith("[") and "]" in msg:
            bracket_end = msg.index("]")
            tag = msg[1:bracket_end]
            if tag in _STAGE_COLORS:
                record.msg = _colorize(tag, msg[bracket_end + 2:])
                record.args = None  # already formatted
        return super().format(record)


def is_verbose() -> bool:
    """Return *True* when the operator has opted into verbose output."""
    return os.environ.get("LUMINA_VERBOSE", "").strip() not in ("", "0", "false")


def install_verbose_handler() -> None:
    """Replace the root handler's formatter with ``ColoredTurnFormatter``.

    Call this early in the server startup path — typically in
    ``server.py`` before routers are mounted — when :func:`is_verbose`
    returns *True*.
    """
    root = logging.getLogger()
    formatter = ColoredTurnFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)
    # Also bump the lumina.verbose logger to DEBUG so stage messages appear
    logging.getLogger("lumina.verbose").setLevel(logging.DEBUG)
