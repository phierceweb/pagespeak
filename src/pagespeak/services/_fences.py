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
from dataclasses import dataclass

from pf_core.log import get_logger

logger = get_logger(__name__)

# 3+ backticks or tildes, optional indent or definition-list marker, optional info string.
_FENCE_RE = re.compile(r"^\s*(?::\s+)?(`{3,}|~{3,})")
_LANGUAGE_TAG_RE = re.compile(r"[A-Za-z{.][\w+#.{}-]*")


def _is_language_tag(info: str) -> bool:
    """`python`, `{.ruby}`, `mermaid pagespeak-image="…"`: a word plus attributes.

    Not the rest of a sentence, link or table row an injected diagram sat in,
    which a closer can carry.
    """
    words = info.split()
    return (
        bool(words)
        and _LANGUAGE_TAG_RE.fullmatch(words[0]) is not None
        and all("=" in w or w[0] in "{.#" for w in words[1:])
    )


@dataclass(frozen=True)
class FencedBlock:
    start: int  # 0-based index of the opening delimiter line
    end: int | None  # the closing delimiter line; None when it has none
    info: str  # the opener's info string, stripped


def fenced_blocks(lines: list[str]) -> list[FencedBlock]:
    """Each top-level fenced block.

    A block opened with backticks is closed only by backticks (and likewise for
    tildes), and per CommonMark only by a run at least as long as the opener,
    which is how a document shows fenced markdown. A delimiter carrying a
    language tag always opens: inside a block it means the block lost its
    closer, so that block ends there with `end=None`. A definition-list
    delimiter (`:   ````) only opens.
    """
    blocks: list[FencedBlock] = []
    start: int | None = None
    fence_char, fence_len, info = "", 0, ""
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if not m:
            continue
        run = m.group(1)
        line_info = line[m.end() :].strip()
        if start is not None:
            if line.lstrip().startswith(":") or run[0] != fence_char or len(run) < fence_len:
                continue
            if not _is_language_tag(line_info):
                blocks.append(FencedBlock(start, i, info))
                start = None
                continue
            blocks.append(FencedBlock(start, None, info))
        start, fence_char, fence_len, info = i, run[0], len(run), line_info
    if start is not None:
        blocks.append(FencedBlock(start, None, info))
    return blocks


def fence_flags(lines: list[str]) -> list[bool]:
    """True for every line inside a fenced block (per `fenced_blocks`), delimiters included."""
    flags = [False] * len(lines)
    blocks = fenced_blocks(lines)
    for k, block in enumerate(blocks):
        if block.end is not None:
            last = block.end
        elif k + 1 < len(blocks):
            last = blocks[k + 1].start - 1
        else:
            last = len(lines) - 1
        for i in range(block.start, last + 1):
            flags[i] = True
    if blocks and blocks[-1].end is None:
        # Everything from the opener is now inert for every caller. Say so:
        # a malformed document silently disabling a whole pass is the failure
        # this project keeps re-learning.
        opened_at = blocks[-1].start + 1
        opener = _FENCE_RE.match(lines[blocks[-1].start])
        logger.warning(
            "fence_unclosed_at_eof line=%d delimiter=%s inert_lines=%d",
            opened_at,
            opener.group(1) if opener else "",
            len(lines) - opened_at + 1,
        )
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
