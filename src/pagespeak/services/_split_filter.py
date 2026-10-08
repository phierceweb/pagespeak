"""Section-set filtering for the splitter: TOC-phantom dropping, empty-body
selection (with chapter-shell preservation), and on-disk filename-collision
dedup.

Imports `_Section` / `_Collision` from `_split_parse` and
`_section_output_path` from `_split_write`; the orchestrator calls into here.
"""

from __future__ import annotations

import re
from pathlib import Path

from pf_core.log import get_logger

from ._heading_sanity import is_toc_phantom_heading
from ._split_parse import _PAGE_ANCHOR_LINE_RE, _Collision, _Section
from ._split_write import _section_output_path

logger = get_logger(__name__)

_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")

# A TOC entry's "body" is at most a page anchor; anything longer is content
# a subtree prune would destroy.
_PHANTOM_BODY_CHARS = 40

_NAV_LINK_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+)?\[[^\]]+\]\([^)\s]*\)\s*$")
_NAV_LIST_MIN_LINKS = 2
_NAV_LIST_MIN_RATIO = 0.8


def _is_nav_list_body(section: _Section) -> bool:
    """True if the section's body is essentially a table-of-contents link list."""
    lines = [line for line in section.content_lines if line.strip()]
    if not lines:
        return False
    links = sum(1 for line in lines if _NAV_LINK_LINE_RE.match(line))
    return links >= _NAV_LIST_MIN_LINKS and links / len(lines) >= _NAV_LIST_MIN_RATIO


def _reparent_nav_list_children(sections: list[_Section]) -> int:
    """Stop a contents list from parenting the document.

    When content headings sit one level below a `## Table of Contents`, level
    nesting makes every real section its descendant — burying the manual and
    leaving `INDEX.md` with nothing useful. Such a heading is navigation, never
    a container, so its children are re-attached to its own parent (in document
    order). The contents section itself is kept; nothing is dropped.

    Returns the number of sections whose children were promoted.
    """
    promoted = 0
    for section in list(sections):
        if not section.children or not _is_nav_list_body(section):
            continue
        children = list(section.children)
        section.children = []
        parent = section.parent
        for child in children:
            child.parent = parent
        if parent is not None:
            at = parent.children.index(section) + 1
            parent.children[at:at] = children
        promoted += 1
    return promoted


def _has_substantive_body(section: _Section, *, min_body_chars: int) -> bool:
    """True if the section has enough non-trivial body content to justify
    its own file. Front-matter TOC entries (e.g. `# 1 Introduction 31`)
    end up as section headings with empty bodies — those should be folded
    away rather than emitted as standalone shell files.

    Page-anchor-only lines (`<span id="page-28-14"></span>`) are structural
    furniture, not content, yet a single one is ~30 chars — enough to clear
    the default cutoff on its own. They, and thematic breaks (`---`), are
    excluded from the measure so a heading whose only "body" is furniture is
    treated as an orphan shell."""
    real_lines = [
        line
        for line in section.content_lines
        if not _PAGE_ANCHOR_LINE_RE.match(line.strip()) and not _THEMATIC_BREAK_RE.match(line)
    ]
    body = "\n".join(real_lines).strip()
    return len(body) >= min_body_chars


def _drop_toc_phantom_sections(
    sections: list[_Section],
) -> tuple[list[_Section], int]:
    """Filter out sections whose heading is a TOC-entry promote.

    Marker promotes front-matter TOC / chapter-end summary list items
    into headings shaped like `20.2. Foo, p. 596` or `1.1 Foo 32`.
    These duplicate the real subsection content. The detection logic
    lives in `_heading_sanity.is_toc_phantom_heading`.

    The shape alone is not enough. A chapter-review summary restates its
    subsection with a page back-reference and then carries unique prose, and a
    real title can simply end in a number (`2.4 IEEE 802.11`). A true TOC entry
    has no body, so a phantom-shaped heading whose SUBTREE holds real content is
    kept — dropping is a subtree prune, and content is not recoverable after it.

    Filtering happens BEFORE empty-body filtering so the
    `split_dropped_empty_sections` count reflects real content, not
    TOC bloat.

    Returns `(kept, dropped_count)`.
    """
    kept_ids: set[int] = set()

    def _subtree_has_content(section: _Section) -> bool:
        if _has_substantive_body(section, min_body_chars=_PHANTOM_BODY_CHARS):
            return True
        return any(_subtree_has_content(c) for c in section.children)

    def _walk(section: _Section) -> None:
        # Use `display_name` (number + title) so the "Chapter N <title>"
        # and "N.M <title>" prefix-based rules in is_toc_phantom_heading
        # see the full shape, not just the post-prefix title.
        if is_toc_phantom_heading(section.display_name) and not _subtree_has_content(section):
            logger.info("split_toc_phantom_dropped title=%r", section.display_name)
            return  # Drop this section AND any descendants — implicit prune.
        kept_ids.add(id(section))
        for child in section.children:
            _walk(child)

    for s in sections:
        _walk(s)

    if len(kept_ids) == len(sections):
        return sections, 0

    # Filter the flat list and each parent's children list.
    kept = [s for s in sections if id(s) in kept_ids]
    for s in kept:
        s.children = [c for c in s.children if id(c) in kept_ids]
    dropped = len(sections) - len(kept)
    return kept, dropped


def _select_kept_sections(
    sections: list[_Section], *, min_body_chars: int
) -> tuple[list[_Section], set[int]]:
    """Pick sections to keep. A section is kept if its body clears the
    cutoff OR any of its descendants is kept (chapter-shell preservation).

    Iterating in reverse — leaves before parents — lets a single pass
    propagate "I have a kept descendant" up the chain. Without this,
    `# 2. INSTALLATION` (empty body, has substantive subsections)
    would be dropped, leaving its children with a dangling parent ref
    and a broken breadcrumb.

    Returns the kept list (in original document order) and the set of
    `id()`s for fast membership tests.
    """
    kept_ids: set[int] = set()
    for s in reversed(sections):
        has_body = _has_substantive_body(s, min_body_chars=min_body_chars)
        has_kept_child = any(id(c) in kept_ids for c in s.children)
        if has_body or has_kept_child:
            kept_ids.add(id(s))
    kept = [s for s in sections if id(s) in kept_ids]
    return kept, kept_ids


def _filter_children_to_kept(kept: list[_Section], kept_ids: set[int]) -> None:
    """Each kept section's `children` list is pruned to only kept children
    so the `## Subsections` block doesn't link to dropped files.

    Parent refs are NOT rewritten — a kept section's `parent` may still
    point to a dropped intermediate. The breadcrumb walker uses
    `kept_ids` to render dropped ancestors as plain text rather than
    skipping them, so the chapter title still appears in descendants'
    breadcrumbs even when the chapter file itself wasn't written.
    """
    for s in kept:
        s.children = [c for c in s.children if id(c) in kept_ids]


def _filter_english_subtrees(
    all_sections: list[_Section], writable_sections: list[_Section]
) -> tuple[list[_Section], int]:
    """Drop every writable section that belongs to a non-English subtree.

    A multilingual document organizes each translation as its own branch,
    each with the real content as short descendant sections; some tuck a
    per-language regulatory block under an otherwise-English chapter. Judging
    each section in isolation misses both: a terse translated leaf is too
    short for the language classifier to call.

    So we walk the parsed tree from its roots and classify each section by
    its WHOLE subtree's aggregated text. A subtree that reads non-English
    is dropped wholesale (every writable member). A subtree that reads
    English is kept, but we RECURSE into its children so a non-English
    branch nested under an English chapter is still caught. The aggregate
    of a full translation is long enough for a confident call where a
    single fragment is not; recursion bottoms out at leaves, where the
    classifier's keep-short-sections floor protects terse English.

    The tree is reconstructed from ``parent`` links (which survive the
    child-list pruning that TOC-phantom and min-body filtering do); a
    section whose parent was dropped upstream is treated as its own root.
    ``all_sections`` is the full parsed list (including ancestor-only
    language roots and min-body-dropped members) so each aggregate sees
    the complete branch text; ``writable_sections`` is the set actually
    filtered.

    Returns ``(english_writable_sections, dropped_count)``.
    """
    from ._language import section_is_non_english

    present = {id(s) for s in all_sections}
    children: dict[int, list[_Section]] = {}
    roots: list[_Section] = []
    for s in all_sections:
        if s.parent is None or id(s.parent) not in present:
            roots.append(s)
        else:
            children.setdefault(id(s.parent), []).append(s)

    text_cache: dict[int, str] = {}

    def _subtree_text(section: _Section) -> str:
        cached = text_cache.get(id(section))
        if cached is not None:
            return cached
        parts = [section.heading_line, *section.content_lines]
        parts.extend(_subtree_text(c) for c in children.get(id(section), []))
        text = "\n".join(parts)
        text_cache[id(section)] = text
        return text

    dropped: set[int] = set()

    def _visit(section: _Section) -> None:
        if section_is_non_english(_subtree_text(section)):
            stack = [section]
            while stack:
                node = stack.pop()
                dropped.add(id(node))
                stack.extend(children.get(id(node), []))
        else:
            for child in children.get(id(section), []):
                _visit(child)

    for root in roots:
        _visit(root)

    english = [s for s in writable_sections if id(s) not in dropped]
    return english, len(writable_sections) - len(english)


def _normalized_body(section: _Section) -> str:
    """Whitespace-collapsed body content, for body-equality comparison.

    Two sections with byte-identical normalized bodies are treated as
    duplicates by the collision resolver and dedup'd; bodies that differ
    are treated as distinct content and kept with a numeric filename
    suffix.
    """
    body = "\n".join(section.content_lines)
    # Collapse all whitespace runs to single spaces and strip — a
    # non-strict but robust equality test that ignores cosmetic
    # whitespace differences between two extractions of the same content.
    return re.sub(r"\s+", " ", body).strip()


def _dedupe_section_paths(
    sections: list[_Section],
    output_dir: Path,
    *,
    nested: bool,
) -> tuple[list[_Section], list[_Collision]]:
    """Resolve on-disk filename collisions between sections.

    Two ``_Section`` objects with the same sanitized filename collide on
    disk — without resolution, document order means whichever is written
    later silently overwrites the earlier. Resolution:

    - **Body-identical collisions** (whitespace-normalized body strings
      compare equal): drop all but the first occurrence. Logged as
      `split_dropped_filename_collision`. Catches a table-of-contents echo
      of a real chapter: two structural headings share a title but the dupe
      has no meaningful body.
    - **Body-distinct collisions** (different content under the same
      title): keep all occurrences. The first keeps the bare filename;
      later occurrences get a numeric `filename_suffix` of `-2`, `-3`,
      etc. in document order. No drop, no log.

    Returns the kept sections (in original document order) and one
    ``_Collision`` record per dropped section.
    """
    by_path: dict[Path, list[_Section]] = {}
    for s in sections:
        path = _section_output_path(s, output_dir, nested=nested)
        by_path.setdefault(path, []).append(s)

    dropped: set[int] = set()
    collisions: list[_Collision] = []
    # Every path a section already owns — including single-member groups, whose
    # names are never suffixed. A suffix must not land on one of these: a
    # document with `Foo`, `Foo` and `Foo 2` would otherwise give the second
    # `Foo` the name `foo-2`, which the third section already owns, and the
    # writer truncates rather than merges.
    claimed: set[Path] = set(by_path)
    for path, group in by_path.items():
        if len(group) == 1:
            continue
        # First occurrence (in document order) is the anchor.
        anchor = group[0]
        anchor_body = _normalized_body(anchor)
        anchor_chars = len(anchor_body)
        next_suffix = 2
        for s in group[1:]:
            s_body = _normalized_body(s)
            if s_body == anchor_body:
                # Body-identical → drop, log as collision.
                dropped.add(id(s))
                collisions.append(
                    _Collision(
                        target_path=path,
                        kept_title=anchor.display_name,
                        kept_body_chars=anchor_chars,
                        dropped_title=s.display_name,
                        dropped_body_chars=len(s_body),
                    )
                )
            else:
                # Body-distinct → numeric suffix, both kept. Skip any suffix
                # whose path another section already owns.
                while True:
                    s.filename_suffix = f"-{next_suffix}"
                    next_suffix += 1
                    candidate = _section_output_path(s, output_dir, nested=nested)
                    if candidate not in claimed:
                        claimed.add(candidate)
                        break

    return [s for s in sections if id(s) not in dropped], collisions
