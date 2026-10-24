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
from docx.text.paragraph import Paragraph
from pw_foundation.log import get_logger

from ..models._models import IngestResult
from ._docx_images import _emit_images
from ._docx_numbering import ORDERED_DEFAULT, WordNumbering, build_level_defs
from ._docx_numpr import paragraph_numbering
from ._docx_para import (
    _doc_has_heading,
    _heading_level,
    _indent_depth,
    _para_left_twips,
    _para_style,
)
from ._docx_quality import (
    demote_nonsection_h1,
    emit_heading,
    strip_heading_emphasis,
)
from ._docx_runs import render_runs
from ._docx_walk import iter_body

logger = get_logger(__name__)


def _count_table_numbering(table: Any, numbering: WordNumbering) -> None:
    """Word counts numbered paragraphs inside a table like any other; a text
    box is a story of its own (and written twice, DrawingML + VML fallback)."""
    for p in table._tbl.iter(qn("w:p")):
        if next(p.iterancestors(qn("w:txbxContent")), None) is not None:
            continue
        para = Paragraph(p, table)
        num = paragraph_numbering(para, _para_style(para))
        if num is not None:
            numbering.advance(num.num_id, num.ilvl)


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

    **List numbering restarts at every emitted heading** — every counter,
    not just the heading's own numbering. Deliberate, and the one place
    this reader knowingly diverges from Word, which continues a sequence
    across an unnumbered ``Heading N``. Two reasons it must stay: it pairs
    with the ``list_stack`` reset below (a continued number under re-based
    nesting reads as an orphan), and `demote_nonsection_h1` rule 2 treats a
    section whose first item is ``>= 2`` as a numbering artefact — continue
    the numbering and that signal inverts, deleting real sections. A heading
    numbered through its style takes its label (``1.1.``) from Word's own
    count instead, which no heading resets.

    `output_dir` reserved for image handling (added later).
    """
    defs = build_level_defs(document)
    numbering = WordNumbering(defs)
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
            _count_table_numbering(item.obj, numbering)
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
        style = _para_style(para)
        hlevel = _heading_level(style.name if style else None)
        imgs = _emit_images(para, output_dir)  # writes files, returns refs
        text = render_runs(para)
        # Numbering on a `Heading N` style is Word's heading numbering (`1.`,
        # `1.1.`), not a list; a numId on the paragraph itself is, unless it
        # continues the style's list (Set Numbering Value, Restart Numbering).
        word_num = paragraph_numbering(para, style)
        np: tuple[int, int] | None = None
        if word_num is not None:
            numbering.advance(word_num.num_id, word_num.ilvl)
            if hlevel is None or (
                word_num.own and not numbering.same_list(word_num.num_id, word_num.style_num_id)
            ):
                np = (word_num.num_id, word_num.ilvl)

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
            ldef = defs.get((num_id, ilvl))
            fmt = ldef.fmt if ldef is not None else ORDERED_DEFAULT
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
                if cur_left is None and ldef is not None:
                    cur_left = ldef.left
                if cur_left is None:
                    cur_left = ilvl * 720
                indent = "    " * _indent_depth(list_stack, cur_left)
                if lines and lines[-1].strip() and not _is_list_line(lines[-1]):
                    lines.append("")
                # Word restarts a level whenever ANY shallower level of the same
                # numbering is used, whatever that level's format — so a bullet
                # parent resets its ordered children too.
                for key in list(counters):
                    if key[0] == num_id and key[1] > ilvl:
                        del counters[key]
                if fmt == "bullet":
                    line = f"{indent}- {text}"
                else:
                    counters[(num_id, ilvl)] = counters.get((num_id, ilvl), 0) + 1
                    line = f"{indent}{counters[(num_id, ilvl)]}. {text}"
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
            label = numbering.label(word_num.num_id, word_num.ilvl) if word_num else ""
            add, made = emit_heading("#" * hlevel, f"{label} {text}" if label and text else text)
            if made:
                _append_heading(add, made)
                title_done = True
                list_stack.clear()  # new section: list nesting restarts
                counters.clear()  # numbering restarts per section
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
                    # Adjacent lines are ONE paragraph in CommonMark: without a
                    # blank the authored paragraph boundary is lost.
                    if text.strip() and lines and lines[-1].strip():
                        lines.append("")
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
        # Only on this path: the fallback above returns MarkItDown output,
        # whose structure is inferred, not read.
        structure_authoritative=True,
    )
