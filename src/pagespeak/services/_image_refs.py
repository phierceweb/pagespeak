"""The shared `![alt](target "title")` parser, and the dangling-ref degrade pass.

Every pass that scans image refs uses `parse_image_refs` / `replace_image_refs`
rather than its own regex, so alt text containing brackets and CommonMark
titles are handled the same way everywhere.

`degrade_missing_image_refs` complements the vision pass: vision resolves refs
whose files exist, this rewrites refs whose LOCAL target is missing into their
alt text so the description survives instead of a broken link. It mirrors the
audit's `dangling_image_ref` rule; external `http`/`data` refs are untouched.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

_TITLE_OPENERS = {'"': '"', "'": "'", "(": ")"}


@dataclass(frozen=True)
class ImageRef:
    """One `![alt](target "title")` occurrence."""

    alt: str
    target: str
    span: tuple[int, int]
    line: int
    title: str | None = None

    def retargeted(self, target: str) -> str:
        """This ref rebuilt with a new destination, title preserved."""
        suffix = f' "{self.title}"' if self.title is not None else ""
        return f"![{self.alt}]({target}{suffix})"


def _alt_end_candidates(text: str, start: int) -> Iterator[int]:
    """Indices just past each `]` that could close the alt, nearest first.

    Not depth-tracking: alt text carries unmatched brackets (`[-3, 5)`), so
    pairing them closes one ref's alt on a later ref's `]`. Stops at a blank
    line so an unclosed `![` cannot run away through the document. Lazy — the
    caller takes the first candidate that parses, and scanning to the blank line
    per ref is quadratic where there is none, as in a table of images.
    """
    i, n = start, len(text)
    while i < n:
        char = text[i]
        if char == "\n" and text[i + 1 : i + 2] == "\n":
            return
        if char == "\\":
            # Never step over a newline, or the blank-line bound above is lost.
            i += 1 if text[i + 1 : i + 2] == "\n" else 2
            continue
        if char == "]":
            yield i + 1
        i += 1


def _scan_destination(text: str, start: int) -> tuple[str, int] | None:
    """`(target, index past it)` for an angle-wrapped or bare destination."""
    n = len(text)
    if start < n and text[start] == "<":
        end = text.find(">", start)
        return (text[start + 1 : end], end + 1) if end >= 0 else None
    i = start
    while i < n and text[i] not in " \t)\n":
        i += 1
    return text[start:i], i


def parse_image_refs(text: str) -> list[ImageRef]:
    """Every image ref in `text`, in document order.

    Handles the two shapes a naive regex gets wrong: brackets inside alt text,
    and a CommonMark title that must not be folded into the target.
    """
    refs: list[ImageRef] = []
    i = line = 0
    scanned = 0
    while (i := text.find("![", i)) >= 0:
        # Accumulate from the previous ref; counting from byte 0 each time is
        # quadratic on an image-dense document.
        line += text.count("\n", scanned, i)
        scanned = i
        parsed = _parse_one(text, i, line + 1)
        if parsed is None:
            i += 2
            continue
        refs.append(parsed)
        i = parsed.span[1]
    return refs


def _parse_one(text: str, start: int, line: int) -> ImageRef | None:
    """Parse the ref beginning at `start`, or None if none does.

    Tries each candidate alt-closer nearest-first and returns the first whose
    `(destination "title")` parses — the shortest valid ref, never a runaway.
    """
    n = len(text)
    for alt_end in _alt_end_candidates(text, start + 2):
        if alt_end >= n or text[alt_end] != "(":
            continue
        alt = text[start + 2 : alt_end - 1]
        # An `![` in the alt that no `]` closes is the real opener — this
        # candidate fused a stray marker with a later ref. Skip so the caller
        # retries from the inner `![`, leaving the prose between untouched.
        nested = alt.rfind("![")
        if nested >= 0 and "]" not in alt[nested + 2 :]:
            continue
        k = alt_end + 1
        while k < n and text[k] in " \t":
            k += 1
        dest = _scan_destination(text, k)
        if dest is None:
            continue
        target, k = dest
        while k < n and text[k] in " \t":
            k += 1
        title: str | None = None
        if k < n and text[k] in _TITLE_OPENERS:
            end = text.find(_TITLE_OPENERS[text[k]], k + 1)
            if end < 0:
                continue
            title = text[k + 1 : end]
            k = end + 1
            while k < n and text[k] in " \t":
                k += 1
        if k >= n or text[k] != ")":
            continue
        return ImageRef(
            alt=alt,
            target=target.strip(),
            span=(start, k + 1),
            line=line,
            title=title,
        )
    return None


def replace_image_refs(text: str, repl: Callable[[ImageRef], str | None]) -> tuple[str, int]:
    """Rewrite each image ref via `repl`; `None` leaves that ref untouched.

    Returns `(rewritten_text, replaced_count)`.
    """
    refs = parse_image_refs(text)
    if not refs:
        return text, 0
    out: list[str] = []
    cursor = count = 0
    for ref in refs:
        start, end = ref.span
        new = repl(ref)
        if new is None:
            continue
        out.append(text[cursor:start])
        out.append(new)
        cursor = end
        count += 1
    if not count:
        return text, 0
    out.append(text[cursor:])
    return "".join(out), count


_EXTERNAL_SCHEMES = ("http://", "https://", "data:")


def degrade_missing_image_refs(text: str, *, base_dir: Path | None) -> tuple[str, int]:
    """Rewrite each `![alt](target)` whose local target is missing on disk.

    Non-empty alt becomes an italic caption `_alt_`; an empty-alt ref is
    dropped. External refs, refs whose target exists, and — when `base_dir`
    is None — all refs are left unchanged. Idempotent (a degraded caption
    carries no `![…](…)` to match again).

    Returns `(rewritten_text, degraded_count)`.
    """
    if base_dir is None:
        return text, 0

    def _repl(ref: ImageRef) -> str | None:
        target = ref.target
        if target.startswith(_EXTERNAL_SCHEMES) or not target:
            return None
        # A `%`-encoded target (`My%20Fig.png`) resolves to its decoded file
        # (`My Fig.png`) — check both so a real image isn't wrongly degraded.
        if (base_dir / target).exists() or (base_dir / unquote(target)).exists():
            return None
        alt = ref.alt.strip()
        return f"_{alt}_" if alt else ""

    return replace_image_refs(text, _repl)
