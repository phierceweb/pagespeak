"""Structural heading hygiene for the python-docx reader.

Post-processing on the structure the reader derives from Word's file
format (`numId`/`ilvl`, `Heading N` styles). Structural only — it never
inspects heading wording; a structure-faithful reader transfers the
author's structure, it doesn't edit their prose.

* :func:`strip_heading_emphasis` — drop redundant bold/italic inside an
  ATX heading.
* :func:`emit_heading` — the lines to append for a heading slot: the
  emphasis-stripped heading, or nothing if empty.
* :func:`demote_nonsection_h1` — demote an ``# `` that is a Word numbering
  artefact (a bodyless shell before the next ``# ``, or one whose first
  body content is a numbered item >= 2, i.e. it interrupted an outer list)
  to plain text. Reasons about body presence + list continuation, not
  wording.
"""

from __future__ import annotations

import re

# `_wrap` in the reader only ever emits `*`-based emphasis; `__`/`_`
# covers any literal Word markdown. 1-3 of either, anywhere in the line.
_EMPHASIS_RE = re.compile(r"\*{1,3}|_{1,3}")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
# A top-level ATX heading line (`# Foo`), exactly one `#`.
_H1_RE = re.compile(r"^# \S")
# An image-only line (`![alt](images/x.png)`) — not substantive body.
_IMAGE_ONLY_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
# A numbered list item, capturing its number (`  2. Proteolysis` -> 2).
_NUM_ITEM_RE = re.compile(r"^\s*(\d+)\. \S")


def strip_heading_emphasis(text: str) -> str:
    """Drop markdown emphasis markers and collapse leftover spaces.

    Bold/italic inside an ATX heading is redundant Markdown — general
    hygiene, not a content judgement."""
    cleaned = _EMPHASIS_RE.sub("", text)
    return _MULTI_SPACE_RE.sub(" ", cleaned).strip()


def emit_heading(hashes: str, raw_text: str) -> tuple[list[str], bool]:
    """Lines to append for a heading slot, and whether one was emitted.

    * Empty after stripping emphasis -> nothing emitted, ``False``.
    * Otherwise an ATX heading with emphasis stripped, ``True``.

    No content/phrase filtering: if Word's structure says this
    paragraph is a heading, it is emitted as one. Faithful, not
    editorial.
    """
    htext = strip_heading_emphasis(raw_text)
    if not htext:
        return [], False
    return [f"{hashes} {htext}", ""], True


def _is_body_line(line: str) -> bool:
    """Substantive content under an ``# `` heading: anything that isn't
    blank, image-only, or a *sibling* ``# `` heading. List items,
    paragraphs, tables, captions AND deeper (``##``+) sub-headings all
    count — a section whose only content is a subsection is still a
    real section (regression: `# Doc` / `## Sub`)."""
    s = line.strip()
    if not s or _H1_RE.match(s):
        return False
    return not _IMAGE_ONLY_RE.match(s)


def demote_nonsection_h1(lines: list[str], *, protected: set[int]) -> list[str]:
    """Demote each ``# `` that is a Word *numbering artefact*, by
    STRUCTURE alone (never by wording):

    1. **No body** before the next ``# `` (only blanks / an image /
       another heading) — a bodyless shell.
    2. **First body content is a list continuation** — the first
       substantive line is a numbered item with number >= 2, i.e. the
       ``# `` interrupted an in-progress outer outline (``2.``
       continues a ``1.`` that preceded the heading). A real section's
       first item would be ``1.`` (or prose, a bullet, a subheading).

    Both -> demote to plain text. ``protected`` indices (the document
    title — legitimately bodyless) are left alone. Only level-1 ``#``
    is touched; deeper ``##``+ count as body so a real ``#`` whose
    only content is a subsection is kept.
    """
    h1_idx = [i for i, ln in enumerate(lines) if _H1_RE.match(ln)]
    out = list(lines)
    for pos, i in enumerate(h1_idx):
        if i in protected:
            continue
        end = h1_idx[pos + 1] if pos + 1 < len(h1_idx) else len(lines)
        first = next(
            (lines[k] for k in range(i + 1, end) if _is_body_line(lines[k])),
            None,
        )
        if first is None:
            out[i] = lines[i][2:].strip()
            continue
        m = _NUM_ITEM_RE.match(first)
        if m and int(m.group(1)) >= 2:
            out[i] = lines[i][2:].strip()
    return out
