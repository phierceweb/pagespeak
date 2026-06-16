from __future__ import annotations

from docx import Document

from pagespeak.backends._docx_table import render_table

_GRID2 = "<w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"


def _tc(inner: str) -> str:
    return f"<w:tc>{inner}</w:tc>"


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _tbl(*rows: str, grid: str = _GRID2) -> str:
    return f"<w:tbl>{grid}{''.join(rows)}</w:tbl>"


def _table(make_docx, xml: str):  # noqa: ANN001,ANN202
    return Document(str(make_docx(document_xml=xml))).tables[0]


def test_simple_2x2_grid(make_docx) -> None:
    xml = _tbl(
        f"<w:tr>{_tc(_p('A'))}{_tc(_p('B'))}</w:tr>",
        f"<w:tr>{_tc(_p('1'))}{_tc(_p('2'))}</w:tr>",
    )
    assert render_table(_table(make_docx, xml)) == [
        "",
        "| A | B |",
        "| --- | --- |",
        "| 1 | 2 |",
        "",
    ]


def test_multi_paragraph_cell_joined_with_br(make_docx) -> None:
    cell = _tc(_p("line1") + _p("line2"))
    xml = _tbl(
        f"<w:tr>{_tc(_p('H1'))}{_tc(_p('H2'))}</w:tr>",
        f"<w:tr>{cell}{_tc(_p('x'))}</w:tr>",
    )
    out = render_table(_table(make_docx, xml))
    assert "| line1<br>line2 | x |" in out


def test_pipe_escaped(make_docx) -> None:
    xml = _tbl(
        f"<w:tr>{_tc(_p('a|b'))}{_tc(_p('B'))}</w:tr>",
        f"<w:tr>{_tc(_p('1'))}{_tc(_p('2'))}</w:tr>",
    )
    out = render_table(_table(make_docx, xml))
    assert "| a\\|b | B |" in out


def test_ragged_row_right_padded(make_docx) -> None:
    xml = _tbl(
        f"<w:tr>{_tc(_p('A'))}{_tc(_p('B'))}</w:tr>",
        f"<w:tr>{_tc(_p('only'))}</w:tr>",
    )
    out = render_table(_table(make_docx, xml))
    assert "| only |  |" in out


def test_one_row_header_and_separator_only(make_docx) -> None:
    xml = _tbl(f"<w:tr>{_tc(_p('A'))}{_tc(_p('B'))}</w:tr>")
    assert render_table(_table(make_docx, xml)) == [
        "",
        "| A | B |",
        "| --- | --- |",
        "",
    ]


def test_zero_rows_returns_empty(make_docx) -> None:
    assert render_table(_table(make_docx, _tbl())) == []


def test_bold_run_in_cell(make_docx) -> None:
    bold = "<w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>B</w:t></w:r></w:p></w:tc>"
    xml = _tbl(
        f"<w:tr>{_tc(_p('H1'))}{_tc(_p('H2'))}</w:tr>",
        f"<w:tr>{bold}{_tc(_p('x'))}</w:tr>",
    )
    out = render_table(_table(make_docx, xml))
    assert "| **B** | x |" in out


def test_vmerge_repeats_origin_value(make_docx) -> None:
    o = (
        '<w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr>'
        "<w:p><w:r><w:t>M</w:t></w:r></w:p></w:tc>"
    )
    cont = "<w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>"
    xml = _tbl(
        f"<w:tr>{_tc(_p('H1'))}{_tc(_p('H2'))}</w:tr>",
        f"<w:tr>{o}{_tc(_p('r1'))}</w:tr>",
        f"<w:tr>{cont}{_tc(_p('r2'))}</w:tr>",
    )
    out = render_table(_table(make_docx, xml))
    assert "| M | r1 |" in out
    assert "| M | r2 |" in out
