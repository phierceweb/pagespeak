"""Structure-faithful DOCX -> markdown emitter (python-docx backend).

Renders Word's explicit element types: Heading styles -> ATX headings,
numbered lists -> nested ordered lists (running numbers), bulleted
lists -> nested unordered lists, runs -> bold/italic, hyperlinks ->
links, tables -> a visible deferred placeholder. Faithful: nothing is
promoted or inferred.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx.oxml.ns import qn
from pf_core.log import get_logger

from ..models._models import IngestResult
from ._docx_quality import (
    demote_nonsection_h1,
    emit_heading,
    strip_heading_emphasis,
)
from ._docx_walk import (
    ORDERED_DEFAULT,
    build_numfmt_map,
    build_numindent_map,
    iter_body,
)

logger = get_logger(__name__)

# Only a genuine `Heading N` paragraph style. Word's `Title` is the
# document-title style, NOT a section heading — it can appear on outline
# paragraphs as noise, and real Title-marked sections are always also at
# outline ilvl0 (which is the heading signal that covers them).
_HEADING_STYLE_RE = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    m = _HEADING_STYLE_RE.match(style_name.strip())
    if not m:
        return None
    return min(int(m.group(1)), 6)


def _numpr(paragraph: Any) -> tuple[int, int] | None:
    ppr = paragraph._p.pPr
    if ppr is None or ppr.numPr is None:
        return None
    npr = ppr.numPr
    if npr.numId is None or npr.ilvl is None:
        return None
    return int(npr.numId.val), int(npr.ilvl.val)


def _wrap(text: str, *, bold: bool, italic: bool) -> str:
    if not text:
        return ""
    if bold and italic:
        return f"***{text}***"
    if bold:
        return f"**{text}**"
    if italic:
        return f"*{text}*"
    return text


def _run_seg(child: Any) -> tuple[str, bool, bool]:
    """One run -> (text, bold, italic)."""
    t = "".join(n.text or "" for n in child.findall(qn("w:t")))
    rpr = child.find(qn("w:rPr"))
    bold = rpr is not None and rpr.find(qn("w:b")) is not None
    italic = rpr is not None and rpr.find(qn("w:i")) is not None
    return t, bold, italic


def _render_runs(paragraph: Any) -> str:
    """Render a paragraph's runs, coalescing adjacent same-format runs.

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

    for child in paragraph._p.iterchildren():
        if child.tag == qn("w:r"):
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
        elif child.tag == qn("w:hyperlink"):
            flush()  # hyperlink is a hard segment boundary
            inner = "".join(n.text or "" for n in child.iter(qn("w:t")))
            rid = child.get(qn("r:id"))
            target = rels[rid].target_ref if rid and rid in rels else ""
            out.append(f"[{inner}]({target})" if target else inner)
    flush()
    return "".join(out).strip()


def _doc_has_heading(document: Any) -> bool:
    """True if the body contains any real heading (numbered outline or
    ``Heading*`` style). Title promotion only fires when one exists."""
    for item in iter_body(document):
        if item.kind == "table":
            continue
        para = item.obj
        if _numpr(para) is not None:
            return True
        if _heading_level(para.style.name if para.style else None) is not None:
            return True
    return False


def _para_left_twips(paragraph: Any) -> int | None:
    """The paragraph's OWN left indent in twips (``w:pPr/w:ind/@w:left``)
    — the direct override Word stores. ``None`` when absent (caller
    falls back to the numbering-level indent, then to ilvl)."""
    ppr = paragraph._p.pPr
    if ppr is None:
        return None
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        return None
    left = ind.get(qn("w:left"))
    if left is None:
        return None
    try:
        return int(left)
    except ValueError:
        return None


def _indent_depth(stack: list[int], left_twips: int) -> int:
    """Relative markdown nesting depth from RESOLVED LEFT INDENT — the
    dimension Word actually lays the visual outline out by (consistent
    across numIds, unlike per-numId ``ilvl``). Monotonic stack of
    indents: shallower pops, deeper pushes, equal is a sibling.
    Mutates ``stack``; returns the new depth (``len(stack) - 1``)."""
    while len(stack) > 1 and left_twips < stack[-1]:
        stack.pop()
    if not stack or left_twips > stack[-1]:
        stack.append(left_twips)
    else:  # equal (sibling) — or the single base level
        stack[-1] = left_twips
    return len(stack) - 1


def _add_image_ref(
    rid: str | None,
    paragraph: Any,
    rels: Any,
    images_dir: Path,
    refs: list[str],
) -> None:
    if not rid or rid not in rels:
        return
    part = rels[rid].target_part
    images_dir.mkdir(parents=True, exist_ok=True)
    target = images_dir / Path(part.partname).name
    stem, suffix = target.stem, target.suffix
    n = 2
    while target.exists() and target.read_bytes() != part.blob:
        target = images_dir / f"{stem}-{n}{suffix}"
        n += 1
    if not target.exists():
        target.write_bytes(part.blob)
    alt = ""
    for docpr in paragraph._p.iter(qn("wp:docPr")):
        alt = docpr.get("descr") or docpr.get("title") or ""
        if alt:
            break
    refs.append(f"![{alt}](images/{target.name})")


_VML_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"


def _emit_images(paragraph: Any, output_dir: Path | None) -> list[str]:
    """Positional ``![alt](images/..)`` refs for inline drawings/pict in
    this paragraph; image bytes written under output_dir/images/."""
    if output_dir is None:
        return []
    refs: list[str] = []
    rels = paragraph.part.rels
    images_dir = output_dir / "images"
    for blip in paragraph._p.iter(qn("a:blip")):
        _add_image_ref(blip.get(qn("r:embed")), paragraph, rels, images_dir, refs)
    for imgdata in paragraph._p.iter(_VML_IMAGEDATA):
        _add_image_ref(imgdata.get(qn("r:id")), paragraph, rels, images_dir, refs)
    return refs


def render_markdown(
    document: Any,
    output_dir: Path | None,
    *,
    outline_heading_depth: int = 0,
) -> str:
    """Render the whole document body to faithful markdown.

    A Word multilevel-list (numbered outline) is RETAINED as a nested
    list — including its main level. **Default 0: the ENTIRE Word
    outline stays a nested list**; the only heading is the document
    title (the non-numbered title paragraph — see the structural
    title rule below), which is not part of the numbered outline.
    ``outline_heading_depth`` is the switch to *override* the outline:
    the top N outline levels are promoted to ATX headings (the
    section spine), deeper levels stay the nested list. ``1`` →
    ``ilvl0`` becomes ``#`` (e.g. "Before you begin"); higher
    promotes more levels. ``pStyle`` (Title/Heading1) on outline
    paragraphs is unreliable noise and ignored — ``ilvl`` is the only
    structural signal. True bullet lists (``w:numFmt=bullet``) are
    always lists.

    `output_dir` reserved for image handling (added later).
    """
    numfmt = build_numfmt_map(document)
    numindent = build_numindent_map(document)
    counters: dict[tuple[int, int], int] = {}
    lines: list[str] = []
    protected: set[int] = set()
    has_heading = _doc_has_heading(document)
    title_done = False
    # Word `ilvl`s currently open as markdown list levels WITHIN the
    # current heading section. Markdown indent is RELATIVE to this
    # stack, not the absolute Word ilvl: the first list item under any
    # heading must start at column 0, else (e.g. a section whose
    # content begins at ilvl2 because ilvl0/1 became the title/`##`)
    # a 4-space-indented line with no list parent renders as an
    # indented CODE BLOCK, not a list (in common markdown renderers).
    # Reset at every heading (new section).
    list_stack: list[int] = []  # resolved left-indent (twips) per open level
    # Index in `lines` of the most recent list-item line. A non-numbered
    # paragraph / image inside the outline (a caption / note / label / link /
    # inline figure between numbered items) is appended INLINE to this line
    # with a single space — no hard return before or after, so every outline
    # item stays exactly one source line. (The original bug: an image on its
    # own line with hard returns around it broke the outline.) `None` = not in
    # a list.
    last_item_idx: int | None = None

    def _is_list_line(ln: str) -> bool:
        s = ln.lstrip()
        return bool(re.match(r"(?:\d+\.|[-*+]) ", s))

    def _append_heading(add: list[str], made: bool) -> None:
        # A heading directly after a non-blank line (a list item or a
        # paragraph) with no separating blank is folded INTO that line
        # by some renderers ("prev line text ## heading text").
        # A heading is a block: separate it with a blank line.
        if made and lines and lines[-1].strip():
            lines.append("")
        lines.extend(add)

    def _emit_block_images(refs: list[str]) -> None:
        # Standalone image (not inside a list): its own block.
        for ref in refs:
            lines.append(ref)
            lines.append("")

    for item in iter_body(document):
        if item.kind == "table":
            from ._docx_table import render_table  # lazy: avoid import cycle

            lines.extend(render_table(item.obj))
            title_done = True
            # A table is CONTENT inside the outline, not a section
            # break: do NOT clear `list_stack` (the outline must
            # survive a table — indent-driven depth then puts the
            # next item at its true depth, parallel to its pre-table
            # siblings). Only reset the inline-fold target so a
            # trailing non-numbered paragraph after the table does
            # not fold into the PRE-table item.
            last_item_idx = None
            continue

        para = item.obj
        np = _numpr(para)
        hlevel = _heading_level(para.style.name if para.style else None)
        imgs = _emit_images(para, output_dir)  # writes files, returns refs
        text = _render_runs(para)

        # A paragraph is a HEADING iff it has a genuine `Heading N`
        # style OR it sits at outline ilvl0. Its LEVEL comes from the
        # outline depth when it is in the outline (ilvl0→`#`,
        # Heading@ilvl1→`##`, Heading@ilvl2→`###`, …) so a
        # Heading-styled sub-section nests UNDER its ilvl0 section
        # (a sibling-`#` would get stripped as body-less by
        # `demote_nonsection_h1`). A genuine Heading with no numPr
        # (simple non-outline docs) keeps its literal style level.
        if np is not None:
            num_id, ilvl = np
            fmt = numfmt.get((num_id, ilvl), ORDERED_DEFAULT)
            if ilvl < outline_heading_depth and fmt != "bullet":
                # The switch: top outline level(s) overridden to the
                # section spine → ATX heading at `ilvl+1`. Default
                # depth=0 = nothing here, the whole outline stays the
                # retained list below. `pStyle` ignored: `ilvl` is
                # the signal.
                level = min(ilvl + 1, 6)
                add, made = emit_heading("#" * level, text)
                _append_heading(add, made)
                title_done = title_done or made
                if made:  # an empty/no-content heading is a spacer —
                    # it must NOT reset the outline (de-nest the rest).
                    list_stack.clear()  # new section: nesting restarts
                    counters.clear()  # numbering restarts per section
                    last_item_idx = None
                _emit_block_images(imgs)
            else:
                # RETAIN the Word outline as a nested list. Nesting
                # depth is driven by the RESOLVED LEFT INDENT — the
                # dimension Word actually lays the outline out by, so
                # it is consistent across numIds (a foreign bullet
                # sub-list with its own ilvl0 still nests at its true
                # visual depth). Source of the indent, in order:
                # the paragraph's own `w:ind/@w:left`; else the
                # numbering level's indent; else an ilvl ½-inch
                # ladder (single-numId docs with no explicit indent).
                cur_left = _para_left_twips(para)
                if cur_left is None:
                    cur_left = numindent.get((num_id, ilvl))
                if cur_left is None:
                    cur_left = ilvl * 720
                indent = "    " * _indent_depth(list_stack, cur_left)
                if lines and lines[-1].strip() and not _is_list_line(lines[-1]):
                    lines.append("")
                if fmt == "bullet":
                    line = f"{indent}- {text}"
                else:
                    counters[(num_id, ilvl)] = counters.get((num_id, ilvl), 0) + 1
                    line = f"{indent}{counters[(num_id, ilvl)]}. {text}"
                    for key in list(counters):
                        if key[0] == num_id and key[1] > ilvl:
                            del counters[key]
                if imgs:  # inline image carried by this list item itself
                    line += " " + " ".join(imgs)
                lines.append(line)
                last_item_idx = len(lines) - 1  # fold target for continuations
                title_done = True
            continue

        if hlevel is not None:
            # Word's `Heading N` style ⇒ a heading. Faithful. BUT an
            # EMPTY heading-styled paragraph (Word spacer — common) is
            # a no-op: it must NOT reset the outline, or it de-nests
            # everything after it (an empty `Heading 1` para between two
            # list items would knock the following item to column 0).
            # Only a real (emitted) heading is a section.
            add, made = emit_heading("#" * hlevel, text)
            if made:
                _append_heading(add, made)
                title_done = True
                list_stack.clear()  # new section: list nesting restarts
                last_item_idx = None
                _emit_block_images(imgs)
                continue
            # empty heading-styled spacer: treat like a non-numbered
            # no-text paragraph — fold any carried image inline into
            # the current list item; NEVER reset the outline state.
            if last_item_idx is not None and imgs:
                lines[last_item_idx] += " " + " ".join(imgs)
            else:
                _emit_block_images(imgs)
            continue

        # Structural document-title rule (no content/bold guessing): in
        # a doc that HAS structure, the first non-empty plain paragraph
        # appearing BEFORE any structural node (numPr / `Heading N`) is
        # the document title — by position. A `Title`-styled paragraph
        # not in a numbering reaches here too and is covered by the
        # same rule. `Title` style INSIDE a numbering is deliberately
        # ignored (unreliable noise; the numbering wins). Exactly one
        # title: once emitted, later candidates are body.
        if not title_done and text and has_heading:
            protected.add(len(lines))
            lines.append("# " + strip_heading_emphasis(text))
            lines.append("")
            title_done = True
            list_stack.clear()
            last_item_idx = None
            _emit_block_images(imgs)
        else:
            # A non-numbered paragraph / image BETWEEN numbered items
            # (a caption / note / reaction label / resource link /
            # inline figure) is appended INLINE to the current list
            # item's line with a single space — NO hard return (no
            # blank line, no `<br>`) before or after. There is then NO
            # separate block, so no renderer can turn it into a code
            # block or de-nest the outline that follows. Outside a
            # list (title area / after a heading) it is a normal block.
            pieces = ([text] if text.strip() else []) + imgs
            if last_item_idx is not None and pieces:
                lines[last_item_idx] += " " + " ".join(pieces)
            else:
                _emit_block_images(imgs)
                if text.strip() or not imgs:
                    lines.append(text)

    lines = demote_nonsection_h1(lines, protected=protected)

    out: list[str] = []
    for ln in lines:
        if ln == "" and out and out[-1] == "":
            continue
        out.append(ln)
    if not out:
        return ""
    return "\n".join(out).strip() + "\n"


def convert_structured(
    path: Path,
    *,
    output_dir: Path | None = None,
    outline_heading_depth: int = 0,
) -> IngestResult:
    """Structure-faithful DOCX backend entry. Hard-fail fallback to
    MarkItDown on any python-docx open/parse error (the ONLY fallback —
    no content heuristic).

    ``outline_heading_depth`` (default 0 = retain the WHOLE Word
    outline as a nested list; only the document title is a heading):
    the switch — how many top outline levels to override into ATX
    headings. See :func:`render_markdown`.
    """
    try:
        from docx import Document

        document = Document(str(path))
        markdown = render_markdown(
            document, output_dir, outline_heading_depth=outline_heading_depth
        )
    except Exception as exc:  # noqa: BLE001 - any python-docx failure -> fallback
        logger.warning(
            "docx_structured_fallback path=%s reason=%s detail=%s",
            path,
            type(exc).__name__,
            exc,
        )
        from ._docx import convert_with_markitdown

        return convert_with_markitdown(path, output_dir=output_dir)

    images: list[Path] = []
    if output_dir is not None:
        img_dir = output_dir / "images"
        if img_dir.is_dir():
            images = sorted(img_dir.iterdir())
    return IngestResult(
        markdown=markdown,
        images=images,
        source_format=path.suffix.lstrip("."),
    )
