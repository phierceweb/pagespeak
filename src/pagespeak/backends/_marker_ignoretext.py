"""Marker's repeated-text remover, keeping one copy of a text it would delete everywhere.

Marker's `IgnoreTextProcessor` drops a page's first or last block when its text
recurs across pages: running headers, but also every copy of a section title
printed atop each page of its section. This keeps the first copy of any text the
remover would leave nowhere in the document; a text with a copy elsewhere is
dropped. Copies are matched as Marker matches them, fuzzily (see
`sole_copies_to_restore`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Annotated, Any

from marker.processors.ignoretext import IgnoreTextProcessor as _MarkerIgnoreTextProcessor
from pw_foundation.log import get_logger
from rapidfuzz import fuzz, process

logger = get_logger(__name__)

_MARKER_PROCESSOR = "marker.processors.ignoretext.IgnoreTextProcessor"
_THIS_PROCESSOR = f"{__name__}.IgnoreTextProcessor"
_FALSE_TEXTS = frozenset({"false", "f", "no", "n", "off", "none", "null", "disabled", ""})


def sole_copies_to_restore(
    marked: Sequence[str], survivors: Sequence[str], *, threshold: float
) -> list[int]:
    """Indices into `marked` (document order) to keep: the first copy of each text
    that matches nothing in `survivors` or an earlier kept copy. An empty text — a
    page number, once Marker strips its digits — is never kept. Matching is
    Marker's own fuzzy match, so two titles a character apart (`Chapter 1
    Overview`, `Chapter 2 Overview`) count as one text and only the first keeps a
    copy; it also folds a note whose page reference varies into one line."""
    kept = list(survivors)
    has_copy = set(kept)
    restore: list[int] = []
    for i, text in enumerate(marked):
        if not text.strip() or text in has_copy:
            continue
        best = process.extractOne(text, kept, scorer=fuzz.ratio)
        if best is None or best[1] <= threshold:
            restore.append(i)
            kept.append(text)
        has_copy.add(text)
    return restore


# Same class name as Marker's: its config keys (`IgnoreTextProcessor_max_streak`)
# are matched by class name.
class IgnoreTextProcessor(_MarkerIgnoreTextProcessor):  # type: ignore[misc]  # marker is untyped
    keep_sole_copy: Annotated[
        bool,
        "Keep the first copy of a text that would otherwise be removed everywhere.",
    ] = True

    def __call__(self, document: Any) -> None:
        blocks = [
            b for page in document.pages for b in page.contained_blocks(document, self.block_types)
        ]
        before = [b.ignore_for_output for b in blocks]
        super().__call__(document)
        if not _as_bool(self.keep_sole_copy):
            return
        marked = [
            b for b, was in zip(blocks, before, strict=True) if b.ignore_for_output and not was
        ]
        if not marked:
            return
        survivors = [
            self.clean_text(b.raw_text(document)) for b in blocks if not b.ignore_for_output
        ]
        restore = sole_copies_to_restore(
            [self.clean_text(b.raw_text(document)) for b in marked],
            survivors,
            threshold=self.text_match_threshold,
        )
        for i in restore:
            marked[i].ignore_for_output = False
        if restore:
            logger.info("marker_repeated_text_first_copy_kept count=%d", len(restore))


def _as_bool(value: object) -> bool:
    """Marker assigns config values untyped; a JSON `"false"` must not read as true."""
    if isinstance(value, str):
        text = value.strip().lower()
        number = _number(text)
        if number is None:
            return text not in _FALSE_TEXTS
        return number != 0 and not math.isnan(number)
    return bool(value)


def _number(text: str) -> float | None:
    for parse in (lambda t: float(int(t, 0)), float):
        try:
            return parse(text)
        except (ValueError, OverflowError):
            continue
    return None


def marker_processor_list(default_processors: Iterable[type]) -> list[str]:
    """Marker's default processors as dotted paths, this remover in place of its own."""
    names = [f"{cls.__module__}.{cls.__name__}" for cls in default_processors]
    return [_THIS_PROCESSOR if name == _MARKER_PROCESSOR else name for name in names]
