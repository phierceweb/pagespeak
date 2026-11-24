"""Layout backend: the whole document — pages read in order into one markdown text, with
the crops it names, then the profile's numbered-stop lists and section nesting applied."""

from __future__ import annotations

import re
from typing import Any

from ._layout_fields import bad
from ._layout_page import classify, flow_chart, is_opener, margin
from ._layout_pictures import PageSource, render_box, render_figure, render_raster
from ._layout_profile import LayoutProfile
from ._layout_table_md import render_table
from ._layout_text import Doc, emit_text, text_lines

Crop = tuple[int, list[float], str, int]


def title_block(d: Doc, src: PageSource, prof: LayoutProfile) -> None:
    """The cover page read for its facts (the lines the profile keeps), with the lines it names on other pages."""
    tb = prof.title_block
    rows: dict[int, list[dict[str, Any]]] = {}
    # the cover is letter-spaced: one line of type comes as several pieces
    for ln in src.page(tb.cover_page)["lines"]:
        rows.setdefault(round(ln["base"]), []).append(ln)
    cover = [
        " ".join(ln["text"].strip() for ln in sorted(ls, key=lambda ln: ln["x0"]))
        for _, ls in sorted(rows.items(), reverse=True)
    ]
    text = ". ".join(t for t in cover if tb.keep.match(t))
    for old, new in tb.replace:
        text = text.replace(old, new)
    parts = [text, *_title_lines(src, prof)]
    d.heading(1, tb.heading)
    if any(parts):
        d.block([". ".join(p for p in parts if p) + "."])


def _title_lines(src: PageSource, prof: LayoutProfile) -> list[str]:
    """The lines from other pages the profile adds to the title block, in its order."""
    out = []
    for i, (page, pattern) in enumerate(prof.title_block.lines):
        found = next((ln for ln in src.page(page)["lines"] if pattern.match(ln["text"])), None)
        if found is None:
            raise bad(
                f"document.title_block.lines[{i}]: no line on page {page} (0-based) matches "
                f"{pattern.pattern!r}"
            )
        out.append(found["text"].strip())
    return out


def numbered_stops(text: str, prof: LayoutProfile) -> str:
    """Under a heading the profile names (`stops_heading`): a route's printed stops and blanks, in order, as a
    numbered list (a table of stops and hints reads the same way, a blank where the stop is to be filled in)."""
    out: list[str] = []
    in_stops, n = False, 0
    for line in text.split("\n"):
        if line.startswith("#"):
            if out and out[-1] != "":
                out.append("")
            in_stops, n = bool(prof.stops_heading.match(line)) and prof.stops_exclude not in line, 0
        elif in_stops and re.fullmatch(r"(\*\*[^*]+\*\*/?)+|_{6}", line):
            n += 1
            out.append(f"{n}. {line}")
            continue
        elif in_stops and re.fullmatch(r"\|( +\|)+|\|(---\|)+", line):
            continue  # the headless table's empty header
        elif in_stops and (m := re.fullmatch(r"\| ([^|]*) \| ([^|]*) \|", line)):
            stop, hint = m.groups()
            n += 1
            out.append(
                f"{n}. {stop.strip() or '______'}" + (f" {hint.strip()}" if hint.strip() else "")
            )
            continue
        elif in_stops and n and line == "":
            continue
        out.append(line)
    return "\n".join(out)


def nest_sections(text: str, prof: LayoutProfile) -> str:
    """Item headings (the profile's `item_heading`) after a topic head are that topic's parts; after an
    aside (`aside_heading`) they stay level with it. With `group_after_empty_head`, a head followed
    directly by another head takes every head after it, to the chapter's end, as its parts."""
    lines = text.split("\n")
    out, inside, grouped = [], False, False
    for i, line in enumerate(lines):
        if line.startswith("# "):
            inside = grouped = False
        elif grouped and line.startswith("##"):
            line = "#" + line
        elif line.startswith("## ") and not prof.item_heading.match(line):
            inside = not prof.aside_heading.search(line)
            nxt = next((x for x in lines[i + 1 :] if x.strip()), "")
            grouped = (
                prof.group_after_empty_head
                and nxt.startswith("## ")
                and not prof.item_heading.match(nxt)
            )
        elif inside and prof.item_heading.match(line):
            line = "#" + line
        out.append(line)
    return "\n".join(out)


def _page_items(
    d: Doc, pg: int, rec: dict[str, Any], chapter: int, src: PageSource, prof: LayoutProfile
) -> tuple[list[Any], dict[int, Any], int]:
    items, floats = flow_chart(rec, prof) if pg in prof.flow_chart_pages else classify(rec, prof)
    if pg in prof.raster_tables:  # the page's picture holds a drawing and a table together
        spec = prof.raster_tables[pg]
        floats = [f for f in floats if f["kind"] != "figure"] + [
            {"kind": "raster", "top": spec["top"], "spec": spec}
        ]
    d.margin = margin([it["line"] for it in items if it["kind"] == "text"])
    if is_opener(rec, prof):
        chapter += 1
        o = prof.opener
        if chapter > len(o.titles):
            raise bad(
                f"page {pg} (0-based) opens chapter {chapter}, but document.opener.titles "
                f"lists {len(o.titles)}"
            )
        d.heading(1, o.heading.format(n=chapter, title=o.titles[chapter - 1]))
        items = [it for it in items if not (it["kind"] == "text" and it["line"]["text"] == o.text)]
    for page_no, pattern in prof.drop_lines:
        if pg == page_no:
            items = [
                it
                for it in items
                if not (it["kind"] == "text" and pattern.match(it["line"]["text"]))
            ]
    for it in items:
        if (
            it["kind"] == "text"
            and chapter == 0
            and it["line"]["text"].strip() in prof.front_headings
        ):
            it["front_h1"] = prof.front_headings[it["line"]["text"].strip()]
    front = [it for it in items if it.get("front_h1")]
    items = [it for it in items if not it.get("front_h1")]
    attached, lines = text_lines(items, prof)
    seq: list[Any] = [("h1", it["line"]["y1"], 0, it["front_h1"]) for it in front]
    # one baseline, one row
    seq += [
        ("text", ln["base"] + 7 if not ln.get("vertical") else ln["y1"], ln["x0"], ln)
        for ln in lines
    ]
    seq += [("blank", it["top"], 0, it) for it in items if it["kind"] == "blank"]
    seq += [(f["kind"], f["top"], 0, f) for f in floats]
    seq.sort(key=lambda s: (-round(s[1], 1), s[2]))
    return seq, attached, chapter


def _emit(
    d: Doc,
    kind: str,
    obj: Any,
    attached: dict[int, Any],
    pg: int,
    fallback: str,
    src: PageSource,
    prof: LayoutProfile,
) -> None:
    if kind == "h1":
        d.heading(1, obj)
    elif kind == "text":
        emit_text(d, obj, attached.get(id(obj)), pg, prof)
    elif kind == "blank":
        d.flush()
        d.out += ["______", ""]
    elif kind == "table":
        render_table(d, obj, pg, src, prof)
    elif kind == "box":
        render_box(d, obj, prof)
    elif kind == "raster":
        render_raster(d, obj["spec"], pg)
    elif kind == "figure":
        render_figure(d, obj, pg, fallback, src, prof)


def build(src: PageSource, prof: LayoutProfile) -> tuple[str, list[Crop]]:
    """The document's markdown and its crops, with the profile's crop overrides applied."""
    d = Doc()
    chapter = 0
    first, last = prof.pages
    for pg in range(first, last + 1):
        if pg == prof.title_block.cover_page:
            title_block(d, src, prof)
            continue
        if pg in prof.skip_pages:
            continue
        seq, attached, chapter = _page_items(d, pg, src.page(pg), chapter, src, prof)
        fallback = prof.opener.picture_label.format(n=chapter) if chapter else "Picture"
        for kind, _, _, obj in seq:
            _emit(d, kind, obj, attached, pg, fallback, src, prof)
    d.end_list()
    text = nest_sections(numbered_stops("\n".join(d.out), prof), prof)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    names = [name for _, _, name, _ in d.crops]
    unknown = sorted(set(prof.crop_overrides) - set(names))
    if unknown:
        raise bad(
            f"document.crop_overrides names no picture of the book: {', '.join(unknown)}; "
            f"its pictures are named like {', '.join(names[:3]) or '(none cut)'}"
        )
    crops = [
        (pg, list(prof.crop_overrides[name]) if name in prof.crop_overrides else box, name, turn)
        for pg, box, name, turn in d.crops
    ]
    return text, crops


def read_pages(prof: LayoutProfile) -> list[int]:
    """The 0-based pages whose text the document reads (the cover gives only the title block)."""
    first, last = prof.pages
    return [
        pg
        for pg in range(first, last + 1)
        if pg not in prof.skip_pages and pg != prof.title_block.cover_page
    ]
