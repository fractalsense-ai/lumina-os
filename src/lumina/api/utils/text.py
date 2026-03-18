"""LaTeX stripping and text normalization utilities."""

from __future__ import annotations

import re

_LATEX_INLINE_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_LATEX_DISPLAY_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_LATEX_DOLLAR2_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_DOLLAR_RE = re.compile(r"\$([^$\n]+)\$")
_LATEX_FRAC_RE = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_LATEX_CMD_BRACE_RE = re.compile(r"\\[a-zA-Z]+\{([^{}]*)\}")


def strip_latex_delimiters(text: str) -> str:
    """Convert LaTeX math notation to plain-text equivalents.

    Removes delimiter pairs (\\(…\\), \\[…\\], $…$, $$…$$), converts
    \\frac{a}{b} → (a)/(b), and strips remaining LaTeX commands with braces
    so the student-facing response never contains raw markup.
    """
    # Display delimiters first (longer pattern takes priority over inline $)
    text = _LATEX_DOLLAR2_RE.sub(r"\1", text)
    text = _LATEX_DISPLAY_RE.sub(r"\1", text)
    # Inline delimiters
    text = _LATEX_DOLLAR_RE.sub(r"\1", text)
    text = _LATEX_INLINE_RE.sub(r"\1", text)
    # \frac{a}{b} → (a)/(b); repeat to handle one level of nesting
    for _ in range(3):
        text = _LATEX_FRAC_RE.sub(r"(\1)/(\2)", text)
    # \left and \right sizing hints — drop entirely
    text = re.sub(r"\\left\s*", "", text)
    text = re.sub(r"\\right\s*", "", text)
    # Common symbols
    text = text.replace(r"\cdot", "*").replace(r"\times", "*")
    # Generic \\cmd{content} → content (catches \text{}, \sqrt{}, etc.)
    text = _LATEX_CMD_BRACE_RE.sub(r"\1", text)
    return text


# Backward-compat alias used by server.py re-export
_strip_latex_delimiters = strip_latex_delimiters
