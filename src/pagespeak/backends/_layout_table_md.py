"""Layout backend: a ruled table into markdown.

The table's title, header and notes are found from its rows; its body becomes rows of a
pipe table, or a list where the table is really one (a fill-in column of terms, a box of
terms set in columns, a single column); a row's drawings are cut as one picture each.
"""

from __future__ import annotations

import re
from typing import Any

from ._layout_pictures import PageSource, picture, text_ceiling
from ._layout_profile import LayoutProfile
from ._layout_table_rows import body_rows, head, key_column, prepare
from ._layout_text import Doc, clean

Row = tuple[Any, ...]


def _emit_lists(d: Doc, tb: dict[str, Any], out_rows: list[Row], cont: bool, fill_in: bool) -> None:
    names, lines = tb["names"], []
    if not fill_in:  # a box of terms to find, set in columns: a list, read down each column
        groups: list[list[Any]] = [["", []]]
        for r in out_rows:
            if r[0] == "section":
                groups.append([r[1], []])
            else:
                groups[-1][1].append(r[1])
        for name, rs in groups:
            terms = [r[c] for c in range(len(tb["data_cols"])) for r in rs if r[c]]
            if name:
                lines.append(f"- **{name}**")
            lines += [("  " if name else "") + "- " + term for term in terms]
        d.block(lines)
        return
    # only the term column is printed: a list keeps the terms' nesting
    if not cont and any(names[1:]):
        lines += ["*Columns:* " + " · ".join(n for n in names if n), ""]
    nested = any(r[0] == "section" for r in out_rows)
    top = sub = False
    for r in out_rows:
        if r[0] == "section":
            caps = re.sub(r"[^A-Za-z]", "", r[1]).isupper()
            sub = top and not caps  # a mixed-case group nests under the capitals group above it
            top = top or caps
            lines.append(("  " if sub else "") + f"- **{r[1]}**")
        else:
            lines.append("  " * (r[2] + (1 if nested else 0) + (1 if sub else 0)) + "- " + r[1][0])
    d.block(lines)


def _emit_pipe_table(d: Doc, tb: dict[str, Any], out_rows: list[Row], cont: bool) -> None:
    names, lines = tb["names"], []
    run_on = cont and d.out_table_end == len(d.out)
    if not run_on:
        lines += ["| " + " | ".join(n or " " for n in names) + " |", "|" + "---|" * len(names)]
    for r in out_rows:
        if r[0] == "section":
            lines.append("| **" + r[1] + "** |" + " |" * (len(names) - 1))
        else:
            row = list(r[1])
            if r[2]:
                row[0] = "— " * r[2] + row[0]
            lines.append("| " + " | ".join(row) + " |")
    if run_on:  # the same table continued from the page before: one table, rows run on
        while d.out and d.out[-1] == "":
            d.out.pop()
        d.out += [*lines, ""]
    else:
        d.block(lines)
    d.out_table_end = len(d.out)


def _grid_terms(tb: dict[str, Any], body: list[list[str]]) -> bool:
    """A headless box of short terms sorted down its columns."""
    down = [r[c].lower() for c in range(len(tb["data_cols"])) for r in body if r[c]]
    return bool(
        tb["header"] is None
        and len(tb["data_cols"]) >= 3
        and len(down) >= 5
        and all(
            len(x) <= 50 and "<br>" not in x and not re.fullmatch(r"\d{1,3}\.?", x) for x in down
        )
        and sum(a <= b for a, b in zip(down, down[1:], strict=False)) >= 0.65 * (len(down) - 1)
    )


def _emit_body(d: Doc, tb: dict[str, Any], out_rows: list[Row], cont: bool) -> None:
    data_cols = tb["data_cols"]
    fill_in = len(data_cols) > 1 and all(
        not any(re.sub(r"[_\s]|<br>", "", x) for x in r[1][1:]) for r in out_rows if r[0] == "row"
    )
    body = [r[1] for r in out_rows if r[0] == "row"]
    if (_grid_terms(tb, body) and not fill_in) or fill_in:
        _emit_lists(d, tb, out_rows, cont, fill_in)
    elif len(data_cols) == 1:
        lines = []
        for r in out_rows:
            if r[0] == "section":
                lines.append(f"- **{r[1]}**")
            elif r[1][0]:
                lines.append("  " * r[2] + "- " + re.sub(r"^• ", "", r[1][0]))
        d.block(lines)
    else:
        _emit_pipe_table(d, tb, out_rows, cont)


def _row_pictures(d: Doc, tb: dict[str, Any], pg: int, src: PageSource) -> None:
    """One picture per row: the drawings of a row's cells together."""
    cells, held, mains = tb["cells"], tb["held"], tb["mains"]
    per_row: dict[int, list[float]] = {}
    row_text: dict[int, list[dict[str, Any]]] = {}
    for k, r in tb["t"].get("pics", []):
        owner = next((j for j in mains if cells[j][4] <= cells[k][4] <= cells[j][5]), None)
        if owner is None or cells[k][4] not in tb["body_rows"]:
            continue  # a title or header cell: only a slice of a taller drawing's box
        ink = src.ink_box(pg, r)
        if ink is None or k in tb["shaded"] or (ink[2] - ink[0]) * (ink[3] - ink[1]) < 400:
            continue  # white page behind a cell's text, or a grey cell: no drawing
        b = per_row.get(owner)
        per_row[owner] = (
            ink
            if b is None
            else [min(b[0], ink[0]), min(b[1], ink[1]), max(b[2], ink[2]), max(b[3], ink[3])]
        )
        row_text.setdefault(owner, []).extend(held[k] + held[owner])
    title = tb["title"]
    for owner in sorted(per_row, key=lambda j: cells[j][4]):
        name = re.sub(r"\*\*|<br>.*", "", tb["texts"][owner])
        label = f"{(title or 'Table').split('.')[0]}: {name}" if name else (title or "Table")
        d.block(
            picture(
                d, pg, per_row[owner], label, ceiling=text_ceiling(per_row[owner], row_text[owner])
            )
        )


def render_table(d: Doc, f: dict[str, Any], pg: int, src: PageSource, prof: LayoutProfile) -> None:
    d.flush()  # a paragraph still being gathered stands between this table and the one before
    tb = prepare(f, prof)
    if tb["t"].get("lead"):
        d.block(
            [
                clean(
                    " ".join(ln["text"] for ln in sorted(tb["t"]["lead"], key=lambda ln: ln["x0"])),
                    prof.checkbox,
                )
            ]
        )
    nums = [x for x in tb["texts"] if x.replace("_", "").strip()]
    # a grid of numbered answer blanks
    if nums and all(re.fullmatch(r"\d{1,3}\.?", x.replace(" ", "").replace("_", "")) for x in nums):
        ns = sorted(int(re.sub(r"\D", "", x)) for x in nums)
        d.block([" ".join(f"{n}. ______" for n in ns)])
        return
    head(tb, prof)
    key_column(tb)
    out_rows = body_rows(tb, prof)
    title, names = tb["title"], tb["names"]
    if title:
        cont = d.last_table == title
        if not cont:
            d.heading(2, title)
    else:  # an untitled, headless table straight after another of the same shape: its next page
        cont = (
            tb["header"] is None
            and d.last_table is None
            and d.out_table_end == len(d.out)
            and d.last_ncols == len(tb["data_cols"])
        )
    d.last_ncols = len(tb["data_cols"])
    # the header again
    out_rows = [
        r
        for r in out_rows
        if not (r[0] == "row" and any(names) and [x.upper() for x in r[1]] == names)
    ]
    notes = tb["notes"]
    # a note row set above the header, repeated on each page
    if notes and not (cont and d.last_notes == notes):
        d.block(
            [
                "*Note:* "
                + prof.note_prefix.sub("", " ".join(n.replace("<br>", " ") for n in notes), count=1)
            ]
        )
    d.last_notes = notes
    _emit_body(d, tb, out_rows, cont)
    _row_pictures(d, tb, pg, src)
    d.last_table = title
