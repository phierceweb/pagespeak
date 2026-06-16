"""Orphan-fragment heading demotion — a cleanup demotion pass.

Demotes short non-prose "fragment" headings sitting at the document's
deepest present heading level: page-margin junk a PDF backend (Marker)
promoted to heading shape — a bare language code (``EN`` / ``FR``), a
short alphanumeric margin code — that is not a real section.

Runs as one pass in the cleanup demotion engine
(``_cleanup_diagnose.HEADING_DEMOTE_PASSES``), with the engine's
``str -> (rewritten, count)`` signature.

Anchor handling is NOT this pass's concern: by the time the demotion
engine runs, ``cleanup_markdown``'s per-line loop has already stripped
each heading's ``<span id="page-X-Y">`` anchor and re-emitted it on the
following line. So a fragment heading reaching here is already
anchor-free, and the plain ``#``-strip demote below leaves the
re-emitted anchor untouched (it sits on its own line and reads as
non-body).

Like the sibling backend-second-guessing passes (empty-shell, bare-int),
this pass is OUTLINE-SKIPPED by the engine: the structure-faithful DOCX
reader's reconstructed headings are trusted, never demoted (the
invariant).
"""

from __future__ import annotations

import re

from ._cleanup import strip_page_spans

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HEADING_DEMOTE_RE = re.compile(r"^(\s*)#{1,6}\s+(.*)$")
_WORD_RE = re.compile(r"\w")
_WS_RUN_RE = re.compile(r"\s+")
_IMAGE_ONLY_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")

# A short max-depth fragment whose proximity-run of fellow short
# max-depth headings reaches this length is an index/glossary divider (a
# back-matter A..Z run), not margin junk → spared. Scattered margin codes
# form runs of length 1 (a real heading sits between successive codes); a
# real alphabetical index forms a run of ~26. 5 sits comfortably between.
FRAGMENT_INDEX_RUN_MIN = 5


def _clean(text: str) -> str:
    """Strip page-anchor spans + collapse whitespace (label matching
    only — does not mutate the rendered document)."""
    return _WS_RUN_RE.sub(" ", strip_page_spans(text)).strip()


def _is_short_fragment(text: str) -> bool:
    """True if `text` is a short non-prose fragment (page-margin junk
    like a bare language code ``EN`` / ``FR``), not a real heading. Bare
    language codes are caught by the ``len <= 3`` rule."""
    t = text.strip()
    if not t:
        return True
    if len(t) <= 3:
        return True
    return not bool(_WORD_RE.search(t))


def _has_substantive_body(lines: list[str], start_idx: int, end_idx: int) -> bool:
    """True if any line strictly between heading ``start_idx`` and the
    next heading ``end_idx`` is real body content.

    A line counts as body when, after stripping page-anchor spans and
    whitespace, it is non-empty, not a heading, not an image-only ref,
    and contains a word character. Any ONE such line spares the heading
    (zero-threshold — wrongly demoting a real heading is far worse than
    sparing rare body-less junk with a stray word)."""
    for line in lines[start_idx + 1 : end_idx]:
        s = strip_page_spans(line).strip()
        if not s:
            continue
        if _HEADING_RE.match(s):
            continue
        if _IMAGE_ONLY_RE.match(s):
            continue
        if _WORD_RE.search(s):
            return True
    return False


def demote_orphan_fragments(text: str) -> tuple[str, int]:
    """Demote short non-prose fragment headings at the deepest present
    heading level — page-margin junk a backend buried.

    A candidate (short text at the max present depth) is demoted only
    when it is genuine margin junk, distinguished from a real short
    heading (glossary term, index divider) by TWO guards — either spares:

    - **Body**: it has substantive body text before the next heading (a
      glossary definition / index entry). Margin codes have none.
    - **Index run**: it belongs to a consecutive run of >=
      ``FRAGMENT_INDEX_RUN_MIN`` short max-depth headings (an
      alphabetical index/glossary). Scattered margin codes run length 1.

    No-op (``count 0``, text returned unchanged) unless >= 2 heading
    depths exist AND >= 1 true fragment survives both guards. Returns
    ``(rewritten_text, demoted_count)``.
    """
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []  # (line_idx, level, clean_text)
    histogram: dict[int, int] = {}
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        headings.append((idx, level, _clean(m.group(2))))
        histogram[level] = histogram.get(level, 0) + 1

    if len(histogram) < 2:
        return text, 0
    max_depth = max(histogram)
    is_frag = [lvl == max_depth and _is_short_fragment(txt) for _, lvl, txt in headings]

    # Run lengths over consecutive fragment headings (index-run guard).
    run_len = [0] * len(headings)
    i = 0
    while i < len(headings):
        if not is_frag[i]:
            i += 1
            continue
        j = i
        while j < len(headings) and is_frag[j]:
            j += 1
        for k in range(i, j):
            run_len[k] = j - i
        i = j

    targets: set[int] = set()
    for h_idx, (line_idx, _lvl, _txt) in enumerate(headings):
        if not is_frag[h_idx]:
            continue
        next_line = headings[h_idx + 1][0] if h_idx + 1 < len(headings) else len(lines)
        if _has_substantive_body(lines, line_idx, next_line):
            continue
        if run_len[h_idx] >= FRAGMENT_INDEX_RUN_MIN:
            continue
        targets.add(line_idx)

    if not targets:
        return text, 0

    out: list[str] = []
    for idx, line in enumerate(lines):
        if idx not in targets:
            out.append(line)
            continue
        m = _HEADING_DEMOTE_RE.match(line)
        # Demote: drop the `#` markers, keep indent + (span-stripped)
        # text. Anchors were already re-emitted on the next line by
        # cleanup's per-line loop, so a plain strip is faithful.
        out.append(f"{m.group(1)}{strip_page_spans(m.group(2)).strip()}" if m else line)
    res = "\n".join(out)
    if text.endswith("\n") and not res.endswith("\n"):
        res += "\n"
    return res, len(targets)


__all__ = ["FRAGMENT_INDEX_RUN_MIN", "demote_orphan_fragments"]
