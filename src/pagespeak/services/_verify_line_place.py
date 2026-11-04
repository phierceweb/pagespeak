"""Where a PDF line sits among a converted document's words, for `line_coverage`.

The output's words are indexed by 4-word run and by word, and run together. A
line counts as present only where its runs point near the cursor and its words
read there one by one, all in order, one perhaps absent or replaced. A place
that needs that one word to differ must lie near where the line before went,
on no words another line holds exactly: shared runs elsewhere in the book
cannot vouch for a lost line, nor can a line one word off it.
Each copy in the output counts once for a line printed twice on one page, or
again after a page without it; a line printed on each of a run of pages (a
table's title over every page it continues on) may share one copy. Image alt
text and Mermaid blocks are not output text here.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ._fences import fenced_blocks
from ._image_refs import replace_image_refs
from ._pdf_lines import UNMAPPED
from ._verify_doc import VerifyDoc, strip_frontmatter

_LATEX_RE = re.compile(r"\\[a-zA-Z]+")
_APOSTROPHE_RE = re.compile(r"[′΄ʹˊ'’`]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DIGITS_RE = re.compile(r"\d+")
_SPACED_LETTERS_RE = re.compile(r"\b[a-z](?: [a-z]){2,}\b")
_BACK, _FORWARD = 25_000, 40_000  # output tokens around the cursor a line may land in
_SLACK = 2  # words the output may add inside a line: a label set inline, a word inserted
_NEAR = 1_000  # output words from the line before that a place needing one word to differ may lie


def tokens(text: str) -> list[str]:
    """Words for matching: accents, apostrophes, markup and 1–2 digit numbers
    dropped; a word holding a glyph the PDF never mapped dropped whole; letters
    set apart (`T W E L V E`) joined back into their word."""
    text = " ".join(w for w in text.split() if UNMAPPED not in w)
    text = _LATEX_RE.sub(" ", text).replace("\xad", "").replace("*", "").replace("_", "")
    text = unicodedata.normalize("NFKD", text.replace("ı", "i"))
    text = _APOSTROPHE_RE.sub("", "".join(c for c in text if not unicodedata.combining(c)))
    text = _SPACED_LETTERS_RE.sub(lambda m: m.group(0).replace(" ", ""), text.lower())
    return [t for t in _TOKEN_RE.findall(text) if not (t.isdigit() and len(t) <= 2)]


def _in(words: list[str], window: list[str]) -> bool:
    rest = iter(window)
    return all(word in rest for word in words)


def _all_but_one(words: list[str], window: list[str]) -> bool:
    """`words` in order in `window`, one of them perhaps absent or replaced."""
    return any(_in(words[:i] + words[i + 1 :], window) for i in range(len(words)))


def _output_tokens(doc: VerifyDoc) -> list[str]:
    lines = strip_frontmatter(doc.master_text).splitlines()
    for block in fenced_blocks(lines):  # a Mermaid transcription repeats the picture's words
        if block.info.lower().startswith("mermaid"):
            end = len(lines) - 1 if block.end is None else block.end
            lines[block.start : end + 1] = [""] * (end + 1 - block.start)
    text, _ = replace_image_refs("\n".join(lines), lambda _ref: " ")
    return tokens(text)


@dataclass
class OutputWords:
    """The output's words, indexed by 4-word run and by word, and the same words
    run together; `claims` holds, per line text, where it was placed and the
    last page that took that place; `held`, the line text each output word was
    placed exactly for; `leaning`, the places found by letting one word differ."""

    words: list[str]
    where: dict[tuple[str, ...], list[int]]
    at: dict[str, list[int]]
    letters: str
    starts: list[int]  # where each word begins in `letters`
    bare: str  # `letters` without digits
    claims: dict[tuple[str, ...], dict[int, int]] = field(default_factory=dict)
    held: dict[int, tuple[str, ...]] = field(default_factory=dict)
    leaning: list[tuple[int, tuple[str, ...], int, str]] = field(default_factory=list)

    @classmethod
    def of(cls, doc: VerifyDoc) -> OutputWords:
        words = _output_tokens(doc)
        where: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for i in range(len(words) - 3):
            where[tuple(words[i : i + 4])].append(i)
        at: dict[str, list[int]] = defaultdict(list)
        starts, offset = [], 0
        for i, word in enumerate(words):
            at[word].append(i)
            starts.append(offset)
            offset += len(word)
        letters = "".join(words)
        return cls(words, where, at, letters, starts, _DIGITS_RE.sub("", letters))

    def holds_letters(self, words: list[str]) -> bool:
        """`words` run together, numbers aside, somewhere in the output."""
        return _DIGITS_RE.sub("", "".join(words)) in self.bare

    def nearby(self, words: list[str], at: int, reach: int) -> int | None:
        """Where `words` stand together within `reach` output words of `at`."""
        positions = self.at.get(words[0], [])
        for p in positions[bisect.bisect_left(positions, at - reach) :]:
            if p > at + reach:
                break
            if self.words[p : p + len(words)] == words:
                return p
        return None

    def place(
        self, inner: list[str], cursor: int, page: int, *, near: int | None = None, line: str = ""
    ) -> list[int] | None:
        """Where near the cursor the line sits, or None when it is not there.

        Where its 4-word runs point, its words must follow in order with at most
        `_SLACK` added among them, one perhaps absent or spelled differently;
        failing that, the line's letters run together (spacing differs), or its
        words in order from where its first word is, one perhaps differing; and
        the place must be `_free`. A place found only by letting one word differ
        must also pass `_may_lean`, measured from `near` (default the cursor)."""
        key = tuple(inner)
        near = cursor if near is None else near
        found = self._runs(inner, cursor, page, near)
        if found is None:
            exact = self._letters(inner, cursor, page) or self._in_order(inner, cursor, page, key)
            found = None if exact is None else (exact[0], False)
        if found is None:
            loose = self._one_off(inner, cursor, page, near)
            found = None if loose is None else (loose[0], True)
        if found is None:
            return None
        start, leans = found
        self.claims.setdefault(key, {})[start] = page
        if leans:
            self.leaning.append((start, key, page, line))
        else:
            for p in range(start, start + len(inner)):
                self.held.setdefault(p, key)
        return [start]

    def overruled(self) -> list[tuple[int, str]]:
        """(page, line) of each place found by letting one word differ whose words
        another line was then placed on exactly."""
        return [(page, line) for start, key, page, line in self.leaning if self._held(key, start)]

    def _free(self, key: tuple[str, ...], start: int, page: int) -> bool:
        """No copy of this text overlapping `start` was last taken by a page other
        than the one before (the module docstring's sharing rule)."""
        return all(
            taken == page - 1 or abs(at - start) >= len(key)
            for at, taken in self.claims.get(key, {}).items()
        )

    def _held(self, key: tuple[str, ...], start: int) -> bool:
        """Another line's text was placed exactly on a word inside this place; not
        its end words, which sit one off when the word that differs is at an end."""
        return any(self.held.get(p, key) != key for p in range(start + 1, start + len(key) - 1))

    def _may_lean(self, key: tuple[str, ...], start: int, near: int) -> bool:
        return abs(start - near) <= _NEAR and not self._held(key, start)

    def _runs(self, inner: list[str], cursor: int, page: int, near: int) -> tuple[int, bool] | None:
        """The best-voted place and whether it needs one word to differ."""
        key = tuple(inner)
        lo, hi = cursor - _BACK, cursor + _FORWARD
        votes: Counter[int] = Counter()
        for i in range(len(inner) - 3):
            positions = self.where.get(tuple(inner[i : i + 4]), [])
            inside = positions[
                bisect.bisect_left(positions, lo) : bisect.bisect_right(positions, hi)
            ]
            votes.update(p - i for p in inside)
        for anchor in sorted(votes, key=lambda a: (-votes[a], abs(a - cursor))):
            window = self.words[max(0, anchor) : anchor + len(inner) + _SLACK]
            if not self._free(key, anchor, page):
                continue
            if _in(inner, window):
                return anchor, False
            if _all_but_one(inner, window) and self._may_lean(key, anchor, near):
                return anchor, True
        return None

    def _in_order(
        self,
        inner: list[str],
        cursor: int,
        page: int,
        key: tuple[str, ...],
        near: int | None = None,
    ) -> list[int] | None:
        """From each copy of the first word: `inner` in order. With `near`, the
        place stands for `key` with one word differing and must pass `_may_lean`."""
        positions = self.at.get(inner[0], [])
        for p in positions[bisect.bisect_left(positions, cursor - _BACK) :]:
            if p > cursor + _FORWARD:
                break
            if (
                _in(inner, self.words[p : p + len(inner) + _SLACK])
                and self._free(key, p, page)
                and (near is None or self._may_lean(key, p, near))
            ):
                return [p]
        return None

    def _one_off(self, inner: list[str], cursor: int, page: int, near: int) -> list[int] | None:
        """The line with one word the build corrected: its other words in order."""
        for i in range(len(inner)):
            found = self._in_order(inner[:i] + inner[i + 1 :], cursor, page, tuple(inner), near)
            if found is not None:
                return found
        return None

    def _letters(self, inner: list[str], cursor: int, page: int) -> list[int] | None:
        if not self.words:
            return None
        run = "".join(inner)
        lo = self.starts[max(0, min(len(self.words) - 1, cursor - _BACK))]
        hi = self.starts[max(0, min(len(self.words) - 1, cursor + _FORWARD))] + len(run)
        at = self.letters.find(run, lo, hi)
        while at >= 0:
            first = bisect.bisect_right(self.starts, at) - 1
            if self._free(tuple(inner), first, page):
                return [first]
            at = self.letters.find(run, at + 1, hi)
        return None
