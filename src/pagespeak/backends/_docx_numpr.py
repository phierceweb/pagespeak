"""Which Word list, at which level, a paragraph is numbered on.

Word stores `numPr` on the paragraph when the author used the toolbar, and on
the paragraph STYLE when they applied a list style or a numbered-heading
template — reading only the former fuses a whole numbered list into one
run-on paragraph.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class ParagraphNumbering(NamedTuple):
    num_id: int
    ilvl: int
    own: bool  # the paragraph names the numId itself
    style_num_id: int | None  # the numId its style chain carries


def _numpr_values(ppr: Any) -> tuple[int | None, int | None]:
    npr = getattr(ppr, "numPr", None) if ppr is not None else None
    if npr is None:
        return None, None
    num_id = int(npr.numId.val) if npr.numId is not None else None
    ilvl = int(npr.ilvl.val) if npr.ilvl is not None else None
    return num_id, ilvl


def paragraph_numbering(paragraph: Any, style: Any) -> ParagraphNumbering | None:
    """The paragraph's Word numbering, or None.

    `numId` and `ilvl` inherit separately: the paragraph's own value, else the
    nearest one up its style's `w:basedOn` chain. `numId` 0 is Word's switch
    for "no numbering", wherever it is set.
    """
    own_num, own_lvl = _numpr_values(paragraph._p.pPr)
    style_num = style_lvl = None
    seen: set[str] = set()
    while style is not None and (style_num is None or style_lvl is None):
        if style.style_id in seen:
            break
        seen.add(style.style_id)
        num, lvl = _numpr_values(getattr(style.element, "pPr", None))
        style_num = num if style_num is None else style_num
        style_lvl = lvl if style_lvl is None else style_lvl
        style = style.base_style
    num_id = own_num if own_num is not None else style_num
    if not num_id:
        return None
    ilvl = own_lvl if own_lvl is not None else style_lvl
    return ParagraphNumbering(num_id, ilvl or 0, own_num is not None, style_num or None)
