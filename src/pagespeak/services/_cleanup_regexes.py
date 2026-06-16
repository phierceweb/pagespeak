"""Shared regex + constant table for the cleanup passes.

A dependency-free leaf so the per-line transforms
(`_cleanup_transforms.py`) and the structural passes
(`_cleanup_structure.py`) can both import these without an import cycle back
through `_cleanup`. No logic here — just compiled patterns and the
empty-section floor.
"""

from __future__ import annotations

import re

CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")

NON_ASCII_CHAR_RE = re.compile(r"[^\x09\x0A\x0D\x20-\x7E]")

HTML_INLINE_TAG_RE = re.compile(r"</?(i|b|strong)>", re.IGNORECASE)

MULTI_SPACE_RE = re.compile(r"\s{2,}")

HEADING_HASH_RE = re.compile(r"^(#+)\s*(.+?)\s*$")

HEADING_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*\.)\s+(.+?)\s*$")

NUMBERED_SECTION_HEADING_RE = re.compile(r"^(\s*)#+\s+(\d+\.\d+(?:\.\d+)*[a-z]?\.?\s+.+?)\s*$")

LIST_O_RE = re.compile(r"^(\s*)-\s*o\s+(.+)$", re.IGNORECASE)

LIST_ALPHA_RE = re.compile(r"^(\s*)-\s*([a-z])\.\s+(.+)$", re.IGNORECASE)

LIST_ROMAN_RE = re.compile(r"^(\s*)-\s*([ivxlcdm]+)\.\s+(.+)$", re.IGNORECASE)

# Some sources label sub-parts ⓐ/ⓑ/ⓒ inside an <ol>, so markitdown stacks its own
# `1.`/`2.`/`3.` on top — `1. ⓐ …`. Strip the redundant ordinal; the circled
# letter is the real sub-label.
CIRCLED_SUBLABEL_LIST_RE = re.compile(r"^(\s*)\d+\.\s+([ⓐ-ⓩ].*)$")

LEADING_WS_RE = re.compile(r"^[ \t]*")

LIST_ITEM_BODY_RE = re.compile(r"^(?:\d+\.|[-*+])\s")

PAGE_SPAN_RE = re.compile(r'<span id="(page-\d+-\d+)"></span>')

IMAGE_ONLY_RE = re.compile(r"^\s*!\[\]\([^)]+\)\s*$")

TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")

TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{2,}.*\|?\s*$")

CROSS_REF_BROKEN_RE = re.compile(r"\[?([A-Za-z][^\]]{1,80})\]?\(#(page-\d+-\d+)\)")

PAGE_REF_RE = re.compile(r"\[([^\]]+)\]\(#(page-\d+-\d+)\)")

TOC_PAGE_NUM_SUFFIX_RE = re.compile(r"\s+\d{1,4}\s*$")

EMPHASIS_MARKER_RE = re.compile(r"\*\*|__")

SCAFFOLD_STUB_MAX_CONTENT_CHARS = 80

HEADING_PAGE_SPAN_RE = re.compile(r'<span\s+id="[^"]*"\s*>\s*</span>')

HEADING_PAGE_LINK_RE = re.compile(r"\[([^\]]+)\]\(#page-\d+-\d+\)")

DANGLING_PAGE_LINK_TAIL_RE = re.compile(r"\]\(#page-\d+-\d+\)")

_WHITESPACE_RUN_RE = re.compile(r"\s+")

_TOC_NUM_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+")
