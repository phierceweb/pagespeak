"""What a table splice must keep: every token a reader sees in the Marker table,
as many times as it appears there.

A token is a number (whole: `7.4`, `1000`, with an attached sign or comparison:
`-5`, `< 5`), a word, or a symbol (`✓`, `$`, `%`, `°`, `×`). Read through, not
counted: `<br>`, HTML tags with quoted attributes (an inline one joins, so
`m<sup>2</sup>` reads `m2`), entities, the target of a link to a page anchor or
URL, `_` and `*` emphasis, thousands separators, the `$` around a LaTeX span and
its formatting commands, and a few LaTeX symbols (`\\times` is `×`). Any other
LaTeX command counts as words. A word a hyphen split at a line break, inside a
cell or across one column's rows, counts whole when the replacement has it whole.
When unsure, a token counts as lost: a refused splice leaves Marker's complete
table in place.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter

from ._table_cells import split_table_row

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ATTRS = r"""(?:\s+[\w-]+=(?:"[^"]*"|'[^']*'))*\s*/?"""
_INLINE_TAG_RE = re.compile(rf"</?(?:sup|sub|b|i|u|em|strong|span|small|mark|a){_ATTRS}>", re.I)
_BLOCK_TAG_RE = re.compile(rf"</?(?:p|div|img|code|pre|ul|ol|li|table|tr|td|th){_ATTRS}>", re.I)
_LINK_TARGET_RE = re.compile(r"\]\((?:#|[a-z]+:|/)[^)\s]*\)")
_LATEX_SPAN_RE = re.compile(r"\$+([^$\n|]*[\\^_{][^$\n|]*)\$+")
# Inside a span: formatting commands, braces, and the `_` / `^` of a sub- or superscript.
_LATEX_MARKUP_RE = re.compile(
    r"\\(?:mathrm|mathbf|mathit|text|textbf|textit|operatorname)\b|[{}_^]"
)
_LATEX_SYMBOLS = {
    "times": "×", "mu": "μ", "pm": "±", "circ": "°", "cdot": "·", "le": "≤", "ge": "≥",
    "leq": "≤", "geq": "≥", "approx": "≈", "alpha": "α", "beta": "β", "gamma": "γ",
    "delta": "δ", "Delta": "Δ",
}  # fmt: skip
_LATEX_SYMBOL_RE = re.compile(r"\\(" + "|".join(map(re.escape, _LATEX_SYMBOLS)) + r")(?![A-Za-z])")
_THOUSANDS_RE = re.compile(r"(?<=\d)[,\u2009\u202f](?=\d{3}\b)")
_MINUS = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2212\ufe63", "-"))
_TOKEN_RE = re.compile(
    r"(?:(?<![^\W_])[-+±<>≤≥] ?)?\d+(?:[.,]\d+)*(?![^\W_])"  # a number, its sign attached
    r"|[^\W_]+"  # a word (letters and digits; `_` separates)
    r"|[^\w\s]"  # one other character, kept when it is a symbol
)
_HYPHEN_BREAK_RE = re.compile(r"(\w+)-\s*<br\s*/?>\s*(\w+)", re.IGNORECASE)
_ABSORBED_SHARE = 0.5


def _plain(s: str) -> str:
    s = _BLOCK_TAG_RE.sub(" ", _INLINE_TAG_RE.sub("", _BR_RE.sub(" ", s)))
    s = _LATEX_SPAN_RE.sub(lambda m: _LATEX_MARKUP_RE.sub("", _symbols(m[1])), s)
    s = _THOUSANDS_RE.sub("", html.unescape(_symbols(_LINK_TARGET_RE.sub("]", s))))
    return unicodedata.normalize("NFKC", s).translate(_MINUS).lower()


def _symbols(s: str) -> str:
    return _LATEX_SYMBOL_RE.sub(lambda m: _LATEX_SYMBOLS[m[1]], s)


def _tokens(s: str) -> list[str]:
    return [t.replace(" ", "") for t in _TOKEN_RE.findall(_plain(s)) if _is_token(t)]


def _is_token(t: str) -> bool:
    if len(t) > 1 or t[0].isalnum():
        return True
    return t != "|" and (unicodedata.category(t) in ("So", "Sm", "Sc") or t in "%‰")


def table_words(s: str) -> set[str]:
    """Every distinct token: words in any script, numbers, symbols."""
    return set(_tokens(s))


def lost_words(original: str, replacement: str) -> tuple[str, ...]:
    """Tokens `original` has more of than `replacement` does."""
    have = Counter(_tokens(replacement))
    counts = Counter(_tokens(original))
    for left, right in _hyphen_splits(original):
        halves = (_tokens(left) or [""])[0], (_tokens(right) or [""])[0]
        joined = halves[0] + halves[1]
        if have[joined] > counts[joined] and all(counts[h] > 0 for h in halves):
            counts.subtract(halves)
            counts[joined] += 1
    return tuple(sorted(t for t, n in counts.items() if n > have[t]))


def _hyphen_splits(table: str) -> list[tuple[str, str]]:
    """Word halves a hyphen split at a line break: `recom-<br>mended` in a cell,
    or a cell ending `recom-` above the same column's `mended`."""
    pairs = [(m[1], m[2]) for m in _HYPHEN_BREAK_RE.finditer(table)]
    rows = [split_table_row(line) for line in table.splitlines() if line.strip().startswith("|")]
    for above, below in zip(rows, rows[1:], strict=False):
        for top, bottom in zip(above, below, strict=False):
            end, start = re.search(r"(\w+)-\s*$", top), re.match(r"\s*(\w+)", bottom)
            if end and start:
                pairs.append((end[1], start[1]))
    return pairs


def absorbs_other_table(original: str, replacement: str, others: list[str]) -> bool:
    """True when `replacement`'s tokens beyond `original`'s hold at least half of a
    neighbouring table's body (its rows below the header): Docling read both
    Marker tables as one, so splicing it over `original` would print the other's
    rows twice."""
    gained = Counter(_tokens(replacement)) - Counter(_tokens(original))
    for other in others:
        body = Counter(_tokens("\n".join(other.splitlines()[1:])))
        if body and sum((body & gained).values()) >= _ABSORBED_SHARE * sum(body.values()):
            return True
    return False
