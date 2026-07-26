"""Fenced-code awareness for line-scanning passes.

A `#` inside a fenced block is a shell comment, a C preprocessor directive, or
a Python comment — never a heading. A pass that rewrites it corrupts the code
and reports the edit indistinguishably from a real fix.

Every whole-text pass that matches headings line-by-line must skip fenced
regions. `apply_outside_fences` makes that the default rather than something
each pass has to remember.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# 3+ backticks or tildes, optional indent, optional info string.
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def fence_flags(lines: list[str]) -> list[bool]:
    """True for every line inside a fenced block, delimiters included.

    A block opened with backticks is closed only by backticks (and likewise for
    tildes), so a `~~~` inside a ``` block does not end it.
    """
    flags: list[bool] = []
    in_fence = False
    fence_char = ""
    for line in lines:
        m = _FENCE_RE.match(line)
        if m:
            char = m.group(1)[0]
            if not in_fence:
                in_fence, fence_char = True, char
            elif char == fence_char:
                in_fence = False
            flags.append(True)  # the delimiter itself is never a heading
            continue
        flags.append(in_fence)
    return flags


def split_by_fences(text: str) -> list[tuple[str, bool]]:
    """`text` as `(segment, is_fenced)` runs, preserving it exactly.

    For block-level passes that cannot work line-by-line. Built on
    `fence_flags`, so tilde fences and mismatched delimiters behave the same
    here as everywhere else — a private `(```.*?```)` regex gets both wrong.
    """
    lines = text.split("\n")
    flags = fence_flags(lines)
    segments: list[tuple[str, bool]] = []
    start = 0
    for i in range(1, len(lines) + 1):
        if i == len(lines) or flags[i] != flags[start]:
            segments.append(("\n".join(lines[start:i]), flags[start]))
            start = i
    return segments


def transform_outside_fences(text: str, transform: Callable[[str], str]) -> str:
    """Apply a whole-block `transform` to each unfenced segment of `text`."""
    return "\n".join(seg if fenced else transform(seg) for seg, fenced in split_by_fences(text))


def apply_outside_fences(text: str, transform: Callable[[str], str]) -> tuple[str, int]:
    """Apply a per-line `transform` to every line outside a fenced block.

    Returns the rewritten text and the number of lines actually changed.
    Preserves a trailing newline.
    """
    lines = text.splitlines()
    flags = fence_flags(lines)
    out: list[str] = []
    changed = 0
    for line, fenced in zip(lines, flags, strict=True):
        if fenced:
            out.append(line)
            continue
        new = transform(line)
        if new != line:
            changed += 1
        out.append(new)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, changed
