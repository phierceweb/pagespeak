"""Size-targeted section packing for the splitter.

Decides per-branch what becomes a section file, from two inputs only —
the heading tree and byte sizes. A subtree that fits `target_bytes` is
ONE file (descendants inlined as content); an oversized node keeps its
own content and recurses into its children; an oversized FLAT node (no
sub-headings) is partitioned at block boundaries into parts that share
its identity (`part_index` / `part_count`, parts 2+ parented to part 1).
A block is a blank-line-separated run; fenced code (which may contain
blank lines) and pipe tables (which contain none) are never cut. No
content heuristics, no per-document level tuning.
"""

from __future__ import annotations

from ._split_parse import _build_heading_line, _Section

_FENCE_PREFIXES = ("```", "~~~")


def _own_size(section: _Section) -> int:
    return len(section.heading_line) + 1 + sum(len(ln) + 1 for ln in section.content_lines)


def _subtree_size(section: _Section) -> int:
    return _own_size(section) + sum(_subtree_size(c) for c in section.children)


def _inline_descendants(section: _Section) -> None:
    """Merge every descendant's heading + content into `section.content_lines`,
    in document order."""

    def _emit(node: _Section) -> None:
        for child in node.children:
            section.content_lines.append("")
            section.content_lines.append(child.heading_line)
            section.content_lines.extend(child.content_lines)
            _emit(child)

    _emit(section)
    section.children = []


def _blocks(lines: list[str]) -> list[list[str]]:
    """Blank-line-separated blocks; a fenced code block stays one block even
    across internal blank lines. Separator blanks are dropped (re-inserted
    between blocks on join)."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    in_fence = False
    for line in lines:
        if not in_fence and not line.strip():
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(line)
        if line.lstrip().startswith(_FENCE_PREFIXES):
            in_fence = not in_fence
    if cur:
        blocks.append(cur)
    return blocks


def _partition(section: _Section, target_bytes: int) -> list[_Section]:
    """Split an oversized section's own content at block boundaries into
    `(part i of k)` sections. Mutates `section` into part 1 (identity, id,
    and filename unchanged); parts 2+ are new sections parented to it.
    Returns `[section]` unchanged when everything fits one part (e.g. a
    single giant block — a block is never cut)."""
    parts_lines: list[list[str]] = []
    cur: list[str] = []
    cur_size = 0
    for block in _blocks(section.content_lines):
        block_size = sum(len(ln) + 1 for ln in block) + 1
        if cur and cur_size + block_size > target_bytes:
            parts_lines.append(cur)
            cur = []
            cur_size = 0
        if cur:
            cur.append("")
        cur.extend(block)
        cur_size += block_size
    if cur:
        parts_lines.append(cur)
    if len(parts_lines) <= 1:
        return [section]

    count = len(parts_lines)
    section.content_lines = parts_lines[0]
    section.part_index = 1
    section.part_count = count
    parts = [section]
    for i, lines in enumerate(parts_lines[1:], start=2):
        title = f"{section.title} (part {i} of {count})"
        part = _Section(
            level=section.level,
            number=section.number,
            title=title,
            heading_line=_build_heading_line("#" * section.level, section.number, title),
            content_lines=lines,
        )
        part.parent = section
        part.part_index = i
        part.part_count = count
        parts.append(part)
    return parts


def _pack(node: _Section, target_bytes: int) -> list[_Section]:
    if _subtree_size(node) <= target_bytes:
        _inline_descendants(node)
        return [node]
    children = node.children
    if not children:
        parts = _partition(node, target_bytes)
        node.children = parts[1:]
        return parts
    out: list[_Section] = [node]
    if _own_size(node) > target_bytes:
        # Oversized intro before the first child heading: partition it; the
        # extra parts become the node's leading children.
        parts = _partition(node, target_bytes)
        node.children = parts[1:] + children
        out.extend(parts[1:])
    for child in children:
        out.extend(_pack(child, target_bytes))
    return out


def pack_sections(sections: list[_Section], *, target_bytes: int) -> list[_Section]:
    """Pack the writable section tree to the size target.

    `sections` is the document-ordered writable list (post-filter, with
    `parent`/`children` links). Returns the new document-ordered writable
    list; sections absorbed into an ancestor's file are gone from it, part
    sections are added."""
    writable_ids = {id(s) for s in sections}
    roots = [s for s in sections if s.parent is None or id(s.parent) not in writable_ids]
    packed: list[_Section] = []
    for root in roots:
        packed.extend(_pack(root, target_bytes))
    return packed
