"""Layout backend: a page's text lines, with font runs, per-character x and type heights.

A line is a dict: ``base``/``x0``/``x1``/``y0``/``y1`` (PDF page space), ``text``,
``runs`` (``[font, text]`` pairs), ``xs`` (each character's left edge), ``h`` (cap
height), ``xh`` (x-height), ``size``, ``font`` (the run with most letters),
``soft_hyphen``; text set at a right angle also carries ``vertical`` and ``up``.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ._layout_chars import Char, deduped, folded, hidden_chars, hidden_runs, page_chars

Line = dict[str, Any]

SUP = dict(zip("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹", strict=True))
_AFTER_NO_SPACE = ",.;:!?)]′’”-–—"
_BEFORE_NO_SPACE = "([‘“-–—/"
_LIGATURE_CODES = "\x0b\x1d\x1e\x1f"


def page_lines(page: Any, textpage: Any, *, acute_as_prime: bool = False) -> list[Line]:
    """The page's lines in text-layer order; lines set at a right angle come last."""
    chars = list(page_chars(textpage))
    runs = hidden_runs(page, textpage)
    if runs:
        drop = hidden_chars(chars, runs)
        chars = [c for i, c in enumerate(chars) if i not in drop]
    # type on a slant or a curve is not read
    chars = [c for c in deduped(chars) if not 0.15 < abs(math.sin(c[8])) < 0.985]
    turned = [c for c in chars if abs(math.sin(c[8])) >= 0.985]
    upright = [c for c in chars if abs(math.sin(c[8])) <= 0.15]
    lines = [
        ln
        for ln in (_finish(ln) for ln in _group(folded(upright, acute_as_prime)))
        if ln is not None
    ]
    return lines + _vertical([c for c in turned if c[0] not in "\r\n\x02"])


def _group(chars: list[Char]) -> list[Line]:
    """Group chars into lines: same baseline (±1.5) and no big horizontal jump."""
    lines: list[Line] = []
    cur: Line | None = None
    for ch, font, x0, x1, y0, y1, base, size, _, _ in chars:
        if ch in "\r\n":
            continue
        if ch in "\x00\x02":
            if cur:
                cur["word_break" if ch == "\x00" else "soft_hyphen"] = True
            continue
        small = (y1 - y0) < 0.8 * max(cur["y1"] - cur["y0"], 1) if cur else False
        same_line = cur is not None and (
            abs(base - cur["base"]) < 1.5 or (small and abs(base - cur["base"]) < 4.5)
        )
        if cur is not None and same_line and _continues(cur, x0):
            _space_before(cur, ch, font, x0, y0, y1)
            cur.pop("word_break", None)
        else:
            if cur:
                lines.append(cur)
            cur = {
                "base": base,
                "x0": x0,
                "x1": x0,
                "y0": y0,
                "y1": y1,
                "text": "",
                "runs": [],
                "soft_hyphen": False,
                "xs": [],
            }
        if ch == " " and not cur["text"]:
            continue
        if ch.isdigit() and small and cur["text"] and base > cur["base"] + 1.2:
            ch = SUP[ch]
        elif (
            ch in "+−"
            and cur["text"]
            and (cur["text"][-1] in "⁰¹²³⁴⁵⁶⁷⁸⁹" or (small and base > cur["base"] + 1.2))
        ):
            ch = "⁺" if ch == "+" else "⁻"  # an ion's charge
        _add_char(cur, ch, font, x0, x1, y0, y1, size)
    if cur:
        lines.append(cur)
    return lines


def _continues(cur: Line, x0: float) -> bool:
    """Whether a char on the current line's baseline runs on from it (wider gaps are column gutters)."""
    ligature = abs(x0 - cur.get("last_x0", -99)) < 0.3  # second letter of a ligature shares its box
    # italic letters overlap ("Yo", "fe")
    kerned = x0 - cur["x1"] > -4 and x0 > cur.get("last_x0", -99) + 0.5
    gap = x0 - cur["x1"]
    return bool((gap < 7 and (gap > -2 or kerned)) or ligature)


def _space_before(cur: Line, ch: str, font: str, x0: float, y0: float, y1: float) -> None:
    """pdfium emits word spaces itself; add one only for a gap wider than kerning can explain."""
    letters = (
        ch.isascii() and ch.isalpha() and cur["text"][-1:].isascii() and cur["text"][-1:].isalpha()
    )
    font_change = (
        bool(cur["runs"])
        and cur["runs"][-1][0] != font
        and ch not in _AFTER_NO_SPACE
        and not (font.startswith("STIX") and cur["runs"][-1][0].startswith("STIX"))
        and cur["text"][-1:] not in _BEFORE_NO_SPACE
    )
    wide = (
        1.4
        if ((font.startswith("STIX") and letters) or font_change)
        else max(3.0, 0.45 * (y1 - y0))
    )
    if ch.isdigit() and cur["text"][-1:].isdigit():
        wide = max(wide, 6.0)  # the two digits of one number (circled "10" sets them apart)
    if (
        (x0 - cur["x1"] > wide or cur.pop("word_break", False))
        and cur["runs"]
        and not cur["text"].endswith(" ")
        and ch != " "
    ):
        cur["runs"][-1][1] += " "
        cur["text"] += " "
        cur["xs"].append(round(x0 - 1, 1))


def _add_char(
    cur: Line, ch: str, font: str, x0: float, x1: float, y0: float, y1: float, size: float
) -> None:
    if not cur["runs"] or cur["runs"][-1][0] != font:
        cur["runs"].append([font, ""])
    cur["runs"][-1][1] += ch
    cur["text"] += ch
    cur["xs"].append(round(x0, 1))
    cur["last_x0"] = x0
    if ch.strip():
        cur["x1"] = max(cur["x1"], x1)
        cur["y0"] = min(cur["y0"], y0)
        cur["y1"] = max(cur["y1"], y1)
        if ch.isupper():
            cur.setdefault("caps", []).append(y1 - y0)
        elif ch in "acemnorsuvwxz":
            cur.setdefault("xhs", []).append(y1 - y0)
        cur.setdefault("sizes", []).append(size)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _finish(ln: Line) -> Line | None:
    """A grouped line's heights, size and main font, with pdfium's spacing quirks repaired."""
    if not ln["text"].strip():
        return None
    ln.pop("last_x0", None)
    caps = ln.pop("caps", [])
    ln["h"] = round(_median(caps), 1) if caps else 0
    xhs = ln.pop("xhs", [])
    ln["xh"] = round(_median(xhs), 2) if xhs else 0
    ln["size"] = round(_median(ln.pop("sizes", [0])), 1)
    ln["font"] = max(ln["runs"], key=lambda r: len(r[1].strip()))[0]
    # pdfium leaves a space between an accented vowel and the hyphen after it
    for m in reversed(list(re.finditer(r"(?<=[^\x00-\x7f]) (?=[-′])", ln["text"]))):
        ln["text"] = ln["text"][: m.start()] + ln["text"][m.end() :]
        del ln["xs"][m.start()]
    for r in ln["runs"]:
        r[1] = re.sub(r"(?<=[^\x00-\x7f]) (?=[-′])", "", r[1])
    if re.search(r"[\x0b\x1d-\x1f]", ln["text"]):
        _expand_ligatures(ln)
    if re.fullmatch(r"\d \d", ln["text"].strip()):  # a circled two-digit number
        i = ln["text"].index(" ")
        ln["text"] = ln["text"][:i] + ln["text"][i + 1 :]
        del ln["xs"][i]
        ln["runs"] = [[r[0], r[1].replace(" ", "")] for r in ln["runs"]]
    lead = len(ln["text"]) - len(ln["text"].lstrip())
    ln["xs"] = ln["xs"][lead : lead + len(ln["text"].strip())]
    ln["text"] = ln["text"].strip()
    for k in ("base", "x0", "x1", "y0", "y1"):
        ln[k] = round(ln[k], 1)
    return ln


def _expand_ligatures(ln: Line) -> None:
    """An "ff" ligature the font maps to a control code."""
    text, xs, skip = "", [], False
    for ch, x in zip(ln["text"], ln["xs"], strict=False):
        if skip and ch == " ":
            skip = False
            continue
        skip = False
        if ch in _LIGATURE_CODES:
            text += "ff"
            xs += [x, x]
            skip = True
        else:
            text += ch
            xs.append(x)
    ln["text"], ln["xs"] = text, xs
    ln["runs"] = [[r[0], re.sub(r"[\x0b\x1d-\x1f] ?", "ff", r[1])] for r in ln["runs"]]


def _vertical(chars: list[Char]) -> list[Line]:
    """Text set at a right angle: one line per column of letters, in reading order."""
    groups: list[dict[str, Any]] = []
    for c in sorted(chars, key=lambda c: (c[9], c[4])):
        cx = c[9]  # the letters' common baseline, as an x position
        g = next((g for g in groups if abs(g["cx"] - cx) < 1.5 and c[4] - g["y1"] < 8), None)
        if g is None:
            groups.append({"cx": cx, "y1": c[5], "chars": [c]})
        else:
            g["chars"].append(c)
            g["y1"] = max(g["y1"], c[5])
    out = []
    for g in groups:
        line = _vertical_line(g["chars"])
        if line is not None:
            out.append(line)
    return out


def _vertical_line(chars: list[Char]) -> Line | None:
    up = math.sin(chars[0][8]) < 0  # pdfium's angle runs clockwise
    cs = sorted(chars, key=lambda c: c[4], reverse=math.sin(chars[0][8]) > 0)
    text, prev = "", None
    for c in cs:
        if c[0] == " ":
            if not text.endswith(" "):
                text += " "
            continue
        # a ligature's halves
        shared = (
            abs(c[4] - prev[4]) < 0.6 and abs(c[5] - prev[5]) < 0.6 if prev is not None else False
        )
        apart = (
            prev is not None
            and not shared
            and min(abs(c[4] - prev[5]), abs(prev[4] - c[5])) > 0.3 * max(c[3] - c[2], 1)
        )
        if apart and not text.endswith(" "):
            text += " "
        text += c[0]
        prev = c
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r" (?=[,.;:)])", "", text)
    text = re.sub(r"(?<=\w) ?- ?(?=\w)", "-", text)
    if not text:
        return None
    x0, x1 = min(c[2] for c in cs), max(c[3] for c in cs)
    y0, y1 = min(c[4] for c in cs), max(c[5] for c in cs)
    font = max(((c[1], sum(1 for d in cs if d[1] == c[1])) for c in cs), key=lambda t: t[1])[0]
    return {
        "base": round((y0 + y1) / 2, 1),
        "x0": round(x0, 1),
        "x1": round(x1, 1),
        "y0": round(y0, 1),
        "y1": round(y1, 1),
        "text": text,
        "runs": [[font, text]],
        "soft_hyphen": False,
        "xs": [round(x0, 1)] * len(text),
        "h": 0,
        "xh": 0,
        "size": round(cs[0][7], 1),
        "font": font,
        "vertical": True,
        "up": up,
    }
