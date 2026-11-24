"""Layout backend: running text into markdown — headings, paragraphs and lists.

`Doc` gathers the output lines as pages are read in order; `emit_text` adds one text
line, deciding from its font, position and the line before whether it is a heading,
a list item, a paragraph's next line or a new paragraph.
"""

from __future__ import annotations

import re
from typing import Any

from ._layout_profile import LayoutProfile

Line = dict[str, Any]

BOLD = re.compile(r"Bold|Bd|Blk|Black|Heavy")
ITAL = re.compile(r"Italic|It\b|It$|Obl|LtIt|MdIt|BdIt")
INDENT_STEP = 17  # points of indent per list level


def clean(t: str, checkbox: str) -> str:
    t = t.replace(checkbox, "").replace("\xad", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ([,.;:)\]])", r"\1", t)
    t = re.sub(r"([(\[]) ", r"\1", t)
    return t.strip()


def styled(line: Line, checkbox: str) -> str:
    """A line's text with bold and italic runs marked."""
    segs: list[list[str]] = []
    for font, text in line["runs"]:
        style = ("**" if BOLD.search(font) else "") + (
            "*" if ITAL.search(font.split("-")[-1]) else ""
        )
        text = text.replace(checkbox, "")
        if segs and segs[-1][0] == style:
            segs[-1][1] += text
        else:
            segs.append([style, text])
    out = ""
    for style, text in segs:
        core = text.strip()
        if not core or not style:
            out += text
            continue
        lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()) :]
        out += f"{lead}{style}{core}{style[::-1]}{trail}"
    out = re.sub(r"\*\*\s*\*\*", " ", out)
    return clean(out, checkbox)


def join(a: str, b: str, soft: bool = False) -> str:
    """Continue a paragraph; a line ending in a soft hyphen or a dash runs straight on."""
    if not a:
        return b
    return a + b if soft or a.endswith(("–", "—")) else a + " " + b


class Doc:
    """The markdown being built, with the state that decides how the next line continues it."""

    def __init__(self) -> None:
        self.out: list[str] = []
        self.para = ""
        self.kind: str | None = None
        self.level = 0
        self.list_x: float | None = None
        self.text_x: float | None = None
        self.prev_base: float | None = None
        self.prev_page: int | None = None
        self.soft = False
        self.last_table: str | None = None
        self.margin: float = 90
        self.text_x_rel: float | None = None
        self.out_table_end = -1
        self.last_notes: list[str] = []
        self.last_ncols: int | None = None
        self.last_list_x: float | None = None
        self.prev_h: float = 0
        self.crops: list[tuple[int, list[float], str, int]] = []

    def flush(self) -> None:
        if self.para:
            # one bold span across a line break
            self.para = re.sub(r"\*\*(\s*)\*\*", r"\1", self.para)
            # one italic span across a line break
            self.para = re.sub(r"(?<=\w)\*(\s+)\*(?=\w)", r"\1", self.para)
            if self.kind == "item":
                self.out.append("  " * self.level + "- " + self.para)
            elif self.kind == "num":
                self.out.append("  " * self.level + self.para)
            else:
                self.out += [self.para, ""]
        self.para, self.kind = "", None
        self.text_x = None

    def end_list(self) -> None:
        self.flush()
        if self.out and self.out[-1] != "":
            self.out.append("")
        if self.list_x is not None:
            self.last_list_x = self.list_x
        self.list_x = None

    def block(self, lines: list[str]) -> None:
        self.end_list()
        self.out += lines
        if self.out and self.out[-1] != "":
            self.out.append("")
        self.last_table = None

    def heading(self, level: int, text: str) -> None:
        self.end_list()
        self.out += ["#" * level + " " + text, ""]
        self.last_table = None


def heading_level(ln: Line, prof: LayoutProfile) -> int | None:
    """The heading level a line in the heading face takes under the profile's rules, else None."""
    t = ln["text"].strip()
    letters = re.sub(r"[^A-Za-z]", "", t)
    if not letters or ln.get("vertical") or not ln["font"].startswith(prof.heading_font):
        return None
    caps, font, h = letters.isupper(), ln["font"], ln.get("h", 0)
    for rule in prof.headings:
        if (
            (not rule.caps or caps)
            and (rule.font_suffix is None or font.endswith(rule.font_suffix))
            and h >= rule.min_cap
            and len(t) < rule.max_len
            and not (rule.no_period and t.endswith("."))
        ):
            return rule.level
    return None


def text_lines(
    items: list[dict[str, Any]], prof: LayoutProfile
) -> tuple[dict[int, Line], list[Line]]:
    """Text items with their list markers attached: (marker by line id, lines) in reading order."""
    lines = [it["line"] for it in items if it["kind"] == "text"]
    marks = [ln for ln in lines if prof.list_mark.match(ln["text"].strip())]
    rest = [ln for ln in lines if ln not in marks]
    attached: dict[int, Line] = {}
    # "3. a. text": the letter takes the text, the number stands alone
    for m in sorted(marks, key=lambda m: -m["x0"]):
        host = min(
            (
                ln
                for ln in rest
                if abs(ln["base"] - m["base"]) < 2
                and 0 < ln["x0"] - m["x1"] < 30
                and id(ln) not in attached
            ),
            key=lambda ln: ln["x0"],
            default=None,
        )
        if host is not None:
            attached[id(host)] = m
        else:
            rest.append(dict(m, lone=True))
    return attached, rest


def _emit_heading(d: Doc, ln: Line, level: int, pg: int, prof: LayoutProfile) -> None:
    mark = "#" * level + " "
    if (
        d.out
        and d.out[-1] == ""
        and len(d.out) >= 2
        and d.out[-2].startswith(mark)
        and d.prev_page == pg
        and d.prev_base is not None
        and 0 < d.prev_base - ln["base"] < 21
        and abs(d.prev_h - ln.get("h", 0)) < 0.5
        and d.kind is None
        and not d.para
    ):
        d.out[-2] += " " + clean(ln["text"], prof.checkbox)  # a head set on two lines
    else:
        d.heading(level, clean(ln["text"], prof.checkbox))
    d.prev_base, d.prev_page, d.prev_h = ln["base"], pg, ln.get("h", 0)


def _start_item(d: Doc, marker: Line, text: str, text_x: float, prof: LayoutProfile) -> None:
    m = marker["text"].strip()
    d.flush()
    x = marker["x0"] - d.margin
    if (
        d.list_x is None
        and re.fullmatch(r"[b-h]\.", m)
        and d.last_list_x is not None
        and x - d.last_list_x > 8
    ):
        # lettered steps running on after a table: still under their number
        d.list_x = d.last_list_x
    if d.list_x is None:
        d.list_x = x
    d.level = max(0, round((x - d.list_x) / INDENT_STEP))
    if m in (prof.checkbox, "•"):
        d.kind, d.para = "item", text
    else:
        d.kind, d.para = "num", f"{m} {text}"
    d.text_x = text_x


def emit_text(d: Doc, ln: Line, marker: Line | None, pg: int, prof: LayoutProfile) -> None:
    level = heading_level(ln, prof)
    if level:
        _emit_heading(d, ln, level, pg, prof)
        return
    text = styled(ln, prof.checkbox)
    if not text:
        return
    # a step number whose text starts with a lettered sub-step
    if ln.get("lone") and re.fullmatch(r"\d{1,2}\.", text):
        marker, text = ln, ""
    text_x = ln["x0"]
    if marker is None and ln["text"].startswith(prof.checkbox):  # a checkbox set in the line itself
        marker = dict(ln, text=prof.checkbox)
        lead = len(ln["text"]) - len(ln["text"][1:].lstrip()) if len(ln["text"]) > 1 else 0
        text_x = ln["xs"][lead] if len(ln.get("xs") or []) > lead else ln["x0"]
    gap = (d.prev_base - ln["base"]) if (d.prev_base is not None and d.prev_page == pg) else 99
    if marker is not None:
        _start_item(d, marker, text, text_x, prof)
    elif (
        d.para
        and d.kind in ("item", "num")
        and d.text_x is not None
        and abs(ln["x0"] - d.text_x) < 4
        and gap < 16
    ):
        d.para = join(d.para, text, d.soft)
    elif (
        d.para
        and d.kind in ("item", "num")
        and d.text_x is not None
        and gap == 99
        and d.text_x_rel is not None
        and abs(ln["x0"] - d.margin - d.text_x_rel) < 4
    ):
        d.para = join(d.para, text, d.soft)  # an item running on over a page break
    elif (
        d.para
        and d.kind == "para"
        and gap < 15
        and d.text_x is not None
        and abs(ln["x0"] - d.text_x) < 12
    ):
        d.para = join(d.para, text, d.soft)
    else:
        if (
            d.kind in ("item", "num")
            and (d.list_x is None or ln["x0"] - d.margin < d.list_x - 4 or gap > 22)
            and gap != 99
        ):
            d.end_list()
        else:
            d.flush()
        d.kind, d.para, d.text_x = "para", text, ln["x0"]
    d.text_x_rel = (d.text_x - d.margin) if d.text_x is not None else None
    d.soft = ln.get("soft_hyphen", False)
    d.prev_base, d.prev_page = ln["base"], pg
