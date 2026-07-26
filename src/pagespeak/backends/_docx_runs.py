"""One paragraph's inline content -> markdown (python-docx backend).

Word nests visible text inside container elements — tracked insertions,
fields, content controls, smart tags, math — not only in bare ``w:r`` runs.
A reader that dispatches on ``w:r`` alone drops every one of them silently,
which is content loss disguised as a clean conversion.
"""

from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn

# Word namespaces. `m:` (OMML) is not in python-docx's `qn` map.
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_M_T = f"{{{_M_NS}}}t"
_M_OMATH = f"{{{_M_NS}}}oMath"
_M_OMATH_PARA = f"{{{_M_NS}}}oMathPara"

# Containers whose children are themselves runs (or more containers). Their
# text is ordinary visible content and is rendered by recursing into them.
#
# `w:ins` is a tracked *insertion* — accepted text, part of the document.
# `w:del` is deliberately absent: its text is `w:delText`, struck from the
# document, and emitting it would put deleted prose back into the output.
_TRANSPARENT = frozenset(
    {
        qn("w:ins"),
        qn("w:sdt"),
        qn("w:sdtContent"),
        qn("w:fldSimple"),
        qn("w:smartTag"),
    }
)


def _wrap(text: str, *, bold: bool, italic: bool) -> str:
    """Emphasise `text`, keeping edge whitespace OUTSIDE the marks.

    CommonMark will not close emphasis on whitespace — `**A **` renders as
    nested `<strong>` rather than bold — and a whitespace-only span
    emphasises nothing. Both arise once `w:tab` contributes real whitespace.
    """
    if not text:
        return ""
    core = text.strip()
    if not core:
        return text  # nothing to emphasise; keep the spacing
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    if bold and italic:
        return f"{lead}***{core}***{trail}"
    if bold:
        return f"{lead}**{core}**{trail}"
    if italic:
        return f"{lead}*{core}*{trail}"
    return text


def _run_seg(child: Any) -> tuple[str, bool, bool]:
    """One run -> (text, bold, italic).

    ``w:tab`` and ``w:br`` carry no text node but are visible separation; a
    run holding ``<w:t>A</w:t><w:tab/><w:t>B</w:t>`` renders ``A B``, never
    the fused ``AB``.
    """
    parts: list[str] = []
    for node in child.iterchildren():
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag in (qn("w:tab"), qn("w:br"), qn("w:cr")):
            parts.append(" ")
        elif node.tag in (qn("w:noBreakHyphen"), qn("w:softHyphen")):
            parts.append("-")
    rpr = child.find(qn("w:rPr"))
    bold = rpr is not None and rpr.find(qn("w:b")) is not None
    italic = rpr is not None and rpr.find(qn("w:i")) is not None
    return "".join(parts), bold, italic


def _math_text(node: Any) -> str:
    """OMML -> plain text. Word stores an equation as `m:t` leaves; joining
    them preserves the formula as readable text rather than dropping it."""
    return "".join(n.text or "" for n in node.iter(_M_T))


def render_runs(paragraph: Any) -> str:
    """Render a paragraph's inline content, coalescing adjacent same-format runs.

    Word stores one visual token (e.g. ``CO2``) as several consecutive
    ``w:r`` runs each with its own ``w:rPr``; wrapping each independently
    shatters it into ``**CO****2**``. Build ``(text, bold, italic)``
    segments, merge neighbours with identical ``(bold, italic)``, drop
    empty-text runs, wrap each merged segment once. Hyperlinks are hard
    segment boundaries (never merged across).
    """
    rels = paragraph.part.rels
    out: list[str] = []
    cur_text = ""
    cur_fmt: tuple[bool, bool] | None = None

    def flush() -> None:
        nonlocal cur_text, cur_fmt
        if cur_fmt is not None and cur_text:
            out.append(_wrap(cur_text, bold=cur_fmt[0], italic=cur_fmt[1]))
        cur_text = ""
        cur_fmt = None

    def emit(text: str) -> None:
        """Append already-rendered text outside the run-merge accumulator."""
        flush()
        if text:
            out.append(text)

    def walk(parent: Any) -> None:
        nonlocal cur_text, cur_fmt
        for child in parent.iterchildren():
            tag = child.tag
            if tag == qn("w:r"):
                text, bold, italic = _run_seg(child)
                if not text:
                    continue  # drop empty-text runs; don't break a merge
                fmt = (bold, italic)
                if cur_fmt is None or fmt == cur_fmt:
                    cur_text += text
                    cur_fmt = fmt
                else:
                    flush()
                    cur_text, cur_fmt = text, fmt
            elif tag == qn("w:hyperlink"):
                flush()  # hyperlink is a hard segment boundary
                inner = "".join(n.text or "" for n in child.iter(qn("w:t")))
                rid = child.get(qn("r:id"))
                target = rels[rid].target_ref if rid and rid in rels else ""
                out.append(f"[{inner}]({target})" if target else inner)
            elif tag in _TRANSPARENT:
                walk(child)  # container: its runs are ordinary content
            elif tag in (_M_OMATH, _M_OMATH_PARA):
                emit(_math_text(child))

    walk(paragraph._p)
    flush()
    return "".join(out).strip()
