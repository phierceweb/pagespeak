"""Body-order traversal for the structure-faithful DOCX backend: yield
body children (paragraphs, tables) in true document order, which
python-docx's `.paragraphs` does not preserve.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass(frozen=True)
class BodyItem:
    """One top-level body child in document order."""

    kind: str  # "paragraph" | "table"
    obj: Any  # docx Paragraph | Table


def iter_body(document: Any) -> Iterator[BodyItem]:
    """Yield paragraphs and tables in true document order. (python-docx
    `.paragraphs` / `.tables` each lose the interleaving.)"""
    yield from _iter_block_children(document.element.body, document)


def _iter_block_children(parent: Any, document: Any) -> Iterator[BodyItem]:
    """Block-level children of `parent`, transparently entering content
    controls. A `w:sdt` wrapping whole paragraphs or tables carries body
    content — skipping it drops the section outright."""
    for child in parent.iterchildren():
        if child.tag == qn("w:p"):
            yield BodyItem("paragraph", Paragraph(child, document))
        elif child.tag == qn("w:tbl"):
            yield BodyItem("table", Table(child, document))
        elif child.tag in (qn("w:sdt"), qn("w:sdtContent")):
            yield from _iter_block_children(child, document)
        # sectPr / bookmarks / other -> skipped (not body content)
