"""
yaml-loader.py — Project Lumina Minimal YAML Loader

A domain-agnostic, standard-library-only YAML loader for use by the D.S.A.
engine and any caller that needs to load YAML-formatted profile or config
files without an external dependency.

Usage:
    from yaml_loader import load_yaml
    profile = load_yaml("path/to/profile.yaml")

The parser handles nested dicts, lists, block mappings as list items,
inline sequences, scalar types
(bool, int, float, null, string), and inline comments.  It is sufficient
for any conforming Project Lumina profile or domain-pack YAML file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _strip_inline_comment(line: str) -> str:
    """Remove a trailing YAML comment (space + #) that is not inside quotes."""
    in_double = False
    in_single = False
    result: list[str] = []
    for i, ch in enumerate(line):
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == "#" and not in_double and not in_single:
            # Only a comment if preceded by whitespace (or at start)
            if i == 0 or line[i - 1] in (" ", "\t"):
                break
        result.append(ch)
    return "".join(result).rstrip()


def _parse_yaml_scalar(s: str) -> Any:
    """Parse a YAML scalar string into a Python value."""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() in ("null", "~", ""):
        return None
    # Inline sequence  [item, item, ...]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(p.strip()) for p in inner.split(",") if p.strip()]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s  # plain string


def _parse_yaml_lines(lines: list[str], pos: list[int]) -> Any:
    """
    Recursive parser for indented YAML blocks.

    `pos` is a one-element list used as a mutable index so recursive calls
    advance the shared position.  Returns the parsed Python value.
    """

    def skip_blank() -> None:
        while pos[0] < len(lines) and not lines[pos[0]].strip():
            pos[0] += 1

    def cur_indent() -> int:
        if pos[0] >= len(lines):
            return -1
        line = lines[pos[0]]
        stripped = line.lstrip()
        return len(line) - len(stripped) if stripped else -1

    skip_blank()
    if pos[0] >= len(lines):
        return None

    line0 = lines[pos[0]]
    stripped0 = line0.lstrip()
    base_indent = len(line0) - len(stripped0)

    if stripped0.startswith("- ") or stripped0 == "-":
        # ── List block ──────────────────────────────────────────
        result: list[Any] = []
        while pos[0] < len(lines):
            skip_blank()
            if pos[0] >= len(lines):
                break
            line = lines[pos[0]]
            stripped = line.lstrip()
            ind = len(line) - len(stripped)
            if ind != base_indent:
                break
            if not (stripped.startswith("- ") or stripped == "-"):
                break
            item_str = stripped[2:].strip()
            pos[0] += 1
            if item_str:
                # Detect block mapping as list item: "- key: val" followed by
                # indented continuation fields ("key2: val2") at a depth greater
                # than the current list's base_indent.  This handles the standard
                # YAML pattern where a sequence contains multi-field mappings.
                colon_idx = item_str.find(":")
                has_mapping_key = (
                    colon_idx > 0
                    and not item_str.startswith('"')
                    and not item_str.startswith("'")
                    and not item_str.startswith("[")
                )
                if has_mapping_key:
                    peek = pos[0]
                    while peek < len(lines) and not lines[peek].strip():
                        peek += 1
                    if peek < len(lines):
                        pk_line = lines[peek]
                        pk_stripped = pk_line.lstrip()
                        pk_ind = len(pk_line) - len(pk_stripped) if pk_stripped else -1
                        if pk_ind > base_indent and not pk_stripped.startswith("- "):
                            first_key = item_str[:colon_idx].strip()
                            first_val_str = item_str[colon_idx + 1:].strip()
                            first_val = _parse_yaml_scalar(first_val_str) if first_val_str else None
                            sub = _parse_yaml_lines(lines, pos)
                            if isinstance(sub, dict):
                                sub[first_key] = first_val
                                result.append(sub)
                            else:
                                result.append(_parse_yaml_scalar(item_str))
                            continue
                result.append(_parse_yaml_scalar(item_str))
            else:
                # Nested mapping/sequence after bare dash
                skip_blank()
                if pos[0] < len(lines):
                    result.append(_parse_yaml_lines(lines, pos))
        return result
    else:
        # ── Mapping block ────────────────────────────────────────
        result_dict: dict[str, Any] = {}
        while pos[0] < len(lines):
            skip_blank()
            if pos[0] >= len(lines):
                break
            line = lines[pos[0]]
            stripped = line.lstrip()
            if not stripped:
                break
            ind = len(line) - len(stripped)
            if ind != base_indent:
                break
            if stripped.startswith("- "):
                break  # list encountered at this level — caller handles it
            if ":" not in stripped:
                pos[0] += 1
                continue
            colon = stripped.index(":")
            key = stripped[:colon].strip()
            val_str = stripped[colon + 1 :].strip()
            pos[0] += 1
            if val_str:
                result_dict[key] = _parse_yaml_scalar(val_str)
            else:
                # Nested block
                skip_blank()
                if pos[0] < len(lines):
                    next_line = lines[pos[0]]
                    next_stripped = next_line.lstrip()
                    next_ind = len(next_line) - len(next_stripped) if next_stripped else -1
                    if next_ind > base_indent:
                        result_dict[key] = _parse_yaml_lines(lines, pos)
                    else:
                        result_dict[key] = None
                else:
                    result_dict[key] = None
        return result_dict


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def load_yaml(path: str | Path) -> dict[str, Any]:
    """
    Load a YAML file and return its contents as a Python dict.

    Uses a minimal built-in parser (no external dependencies).  The parser
    handles nested dicts, lists, inline sequences, scalar types, and inline
    comments.  It is sufficient for any conforming Project Lumina YAML file
    (subject profiles, domain-pack configs, etc.).

    Args:
        path: Path to the YAML file to load.

    Returns:
        A dict representing the top-level YAML mapping, or an empty dict
        if the file does not parse to a mapping.
    """
    with open(path, encoding="utf-8") as fh:
        raw_lines = fh.readlines()

    lines: list[str] = []
    for raw in raw_lines:
        stripped = _strip_inline_comment(raw.rstrip("\n"))
        # Pure-comment lines are converted to blank lines (blank lines are kept
        # to preserve structure signals — _parse_yaml_lines already skips blanks).
        if stripped.lstrip().startswith("#"):
            lines.append("")
        else:
            lines.append(stripped)

    pos = [0]
    result = _parse_yaml_lines(lines, pos)
    return result if isinstance(result, dict) else {}
