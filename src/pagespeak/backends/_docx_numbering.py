"""Word list-number labels (`1.1.`, `II.`, `b)`) for the structure-faithful DOCX backend.

Counts the way Word does: numbering instances over one abstract definition
share a count, one counter per level; using a level advances it and restarts
every deeper level.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from docx.oxml.ns import qn

_PLACEHOLDER_RE = re.compile(r"%([1-9])")
_ROMAN = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)
_FALSE = frozenset({"0", "false", "off"})
# Any numFmt other than "bullet" is an ordered list.
ORDERED_DEFAULT = "decimal"


@dataclass(frozen=True)
class LevelDef:
    """One `w:lvl` of a numbering instance (`w:num`)."""

    fmt: str
    text: str
    start: int
    legal: bool
    left: int | None = None
    # The abstract definition whose count this instance shares.
    list_id: str = ""
    start_override: bool = False


def _as_int(raw: str | None) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _val(el: Any) -> int | None:
    return _as_int(el.get(qn("w:val"))) if el is not None else None


def _level_def(lvl: Any, list_id: str) -> LevelDef:
    fmt_el = lvl.find(qn("w:numFmt"))
    text_el = lvl.find(qn("w:lvlText"))
    legal_el = lvl.find(qn("w:isLgl"))
    ind = lvl.find(f"{qn('w:pPr')}/{qn('w:ind')}")
    start = _val(lvl.find(qn("w:start")))
    return LevelDef(
        fmt=(fmt_el.get(qn("w:val")) if fmt_el is not None else None) or ORDERED_DEFAULT,
        text=(text_el.get(qn("w:val")) if text_el is not None else None) or "",
        start=0 if start is None else start,  # the spec's default when `w:start` is absent
        legal=legal_el is not None and legal_el.get(qn("w:val"), "1") not in _FALSE,
        left=_as_int(ind.get(qn("w:left"))) if ind is not None else None,
        list_id=list_id,
    )


def _numbering_style_nums(document: Any) -> dict[str, int]:
    """Numbering-style id -> the numId its `numPr` names (where a `w:numStyleLink` leads)."""
    try:
        styles = document.styles.element
    except (AttributeError, KeyError, NotImplementedError):
        return {}
    out: dict[str, int] = {}
    for style in styles.findall(qn("w:style")):
        style_id = style.get(qn("w:styleId"))
        num_id = _val(style.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}"))
        if style.get(qn("w:type")) == "numbering" and style_id and num_id is not None:
            out[style_id] = num_id
    return out


def _iter_nums(document: Any) -> Iterator[tuple[int, str, dict[int, Any], dict[int, int]]]:
    """Each `w:num` as (numId, abstract id, ilvl -> `w:lvl`, ilvl -> startOverride),
    following a `w:numStyleLink` to the definition that holds the levels."""
    try:
        numbering_part = document.part.numbering_part
    except (NotImplementedError, KeyError, AttributeError):
        return
    if numbering_part is None:
        return
    root = numbering_part.element

    levels: dict[str, dict[int, Any]] = {}
    style_links: dict[str, str] = {}
    for anum in root.findall(qn("w:abstractNum")):
        aid = anum.get(qn("w:abstractNumId"))
        if aid is None:
            continue
        levels[aid] = {
            ilvl: lvl
            for lvl in anum.findall(qn("w:lvl"))
            if (ilvl := _as_int(lvl.get(qn("w:ilvl")))) is not None
        }
        link = anum.find(qn("w:numStyleLink"))
        if link is not None and link.get(qn("w:val")):
            style_links[aid] = link.get(qn("w:val"))

    nums: dict[int, tuple[str, Any]] = {}
    for num in root.findall(qn("w:num")):
        nid = _as_int(num.get(qn("w:numId")))
        aref = num.find(qn("w:abstractNumId"))
        if nid is not None and aref is not None and aref.get(qn("w:val")) is not None:
            nums[nid] = (aref.get(qn("w:val")), num)

    style_nums = _numbering_style_nums(document) if style_links else {}
    for nid, (aid, num) in nums.items():
        link = style_links.get(aid)
        target = nums.get(style_nums.get(link, -1)) if link else None
        if target is not None:
            aid = target[0]
        overrides = {
            ilvl: start
            for override in num.findall(qn("w:lvlOverride"))
            if (ilvl := _as_int(override.get(qn("w:ilvl")))) is not None
            and (start := _val(override.find(qn("w:startOverride")))) is not None
        }
        yield nid, aid, levels.get(aid, {}), overrides


def build_level_defs(document: Any) -> dict[tuple[int, int], LevelDef]:
    """(numId, ilvl) -> its level definition, with any `w:startOverride` applied.
    Empty when the document has no numbering part."""
    out: dict[tuple[int, int], LevelDef] = {}
    for nid, aid, levels, overrides in _iter_nums(document):
        for ilvl, lvl in levels.items():
            ldef = _level_def(lvl, aid)
            if ilvl in overrides:
                ldef = replace(ldef, start=overrides[ilvl], start_override=True)
            out[(nid, ilvl)] = ldef
    return out


def _letters(value: int) -> str:
    # Word repeats the letter past z (aa, bb, …); it does not count in base 26.
    return chr(ord("a") + (value - 1) % 26) * ((value - 1) // 26 + 1)


def _roman(value: int) -> str:
    out: list[str] = []
    for amount, numeral in _ROMAN:
        count, value = divmod(value, amount)
        out.append(numeral * count)
    return "".join(out)


def format_number(value: int, fmt: str) -> str:
    """`value` in a Word `numFmt`; any format not handled here reads as decimal."""
    if fmt == "none":
        return ""
    if value >= 1 and fmt in ("lowerLetter", "upperLetter"):
        letters = _letters(value)
        return letters.upper() if fmt == "upperLetter" else letters
    if value >= 1 and fmt in ("lowerRoman", "upperRoman"):
        roman = _roman(value)
        return roman.upper() if fmt == "upperRoman" else roman
    if fmt == "decimalZero":
        return f"{value:02d}"
    return str(value)


class WordNumbering:
    """Word's running count for every list in one document."""

    def __init__(self, defs: dict[tuple[int, int], LevelDef]) -> None:
        self._defs = defs
        self._lists = {nid: ldef.list_id for (nid, _), ldef in defs.items() if ldef.list_id}
        self._counts: dict[str, dict[int, int]] = {}
        self._overrides_used: set[tuple[int, int]] = set()

    def _start(self, num_id: int, ilvl: int) -> int:
        ldef = self._defs.get((num_id, ilvl))
        return ldef.start if ldef is not None else 1

    def _list(self, num_id: int) -> str:
        return self._lists.get(num_id, f"#{num_id}")

    def _list_counts(self, num_id: int) -> dict[int, int]:
        return self._counts.setdefault(self._list(num_id), {})

    def same_list(self, num_id: int, other: int | None) -> bool:
        """Whether two numbering instances count as one list (one abstract definition)."""
        return other is not None and self._list(num_id) == self._list(other)

    def advance(self, num_id: int, ilvl: int) -> None:
        """A paragraph used this level: count it and restart every deeper level.

        A `startOverride` restarts the shared count the first time its own
        instance uses the level."""
        counts = self._list_counts(num_id)
        ldef = self._defs.get((num_id, ilvl))
        if ldef is not None and ldef.start_override and (num_id, ilvl) not in self._overrides_used:
            self._overrides_used.add((num_id, ilvl))
            counts[ilvl] = ldef.start
        else:
            counts[ilvl] = counts[ilvl] + 1 if ilvl in counts else self._start(num_id, ilvl)
        for deeper in [level for level in counts if level > ilvl]:
            del counts[deeper]

    def label(self, num_id: int, ilvl: int) -> str:
        """The level's `lvlText` filled from the current counts; "" when it shows no number."""
        ldef = self._defs.get((num_id, ilvl))
        if ldef is None or ldef.fmt == "bullet":
            return ""
        counts = self._list_counts(num_id)

        def fill(match: re.Match[str]) -> str:
            level = int(match.group(1)) - 1
            level_def = self._defs.get((num_id, level))
            fmt = "decimal" if ldef.legal or level_def is None else level_def.fmt
            # A level not yet used under its parent shows one below its start (`0.1`, `1.0.1`).
            value = counts[level] if level in counts else max(self._start(num_id, level) - 1, 0)
            return format_number(value, fmt)

        return _PLACEHOLDER_RE.sub(fill, ldef.text).strip()
