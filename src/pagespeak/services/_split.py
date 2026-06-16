"""Split cleaned markdown into per-section files.

Default mode (`min_level=None`) splits only on numbered headings — designed for
textbook-style docs with numbered sections. Set `min_level=N` to also split on
semantic headings at depth ≥ N (e.g. `## Quick Start`) — designed for product
manuals.

Module layout: parsing → `_split_parse.py`, file/path writing → `_split_write.py`,
section-set filtering → `_split_filter.py`. This module keeps the
`split_into_sections` orchestrator + `DEFAULT_MIN_BODY_CHARS`, and re-exports
`_Section` / `_parse_numbered_heading` / `_detect_fallback_min_level` /
`_build_breadcrumb` so the public + test surface is unchanged.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from pf_core.log import get_logger

from ._cleanup import heading_slug
from ._split_filter import (
    _dedupe_section_paths,
    _drop_toc_phantom_sections,
    _filter_children_to_kept,
    _filter_english_subtrees,
    _select_kept_sections,
)
from ._split_parse import (
    _detect_fallback_min_level as _detect_fallback_min_level,
)
from ._split_parse import (
    _numbered_parse_is_representative,
    _parse_sections,
)
from ._split_parse import (
    _parse_numbered_heading as _parse_numbered_heading,
)
from ._split_parse import (
    _Section as _Section,
)
from ._split_write import (
    _build_breadcrumb as _build_breadcrumb,
)
from ._split_write import (
    _write_index,
    _write_section_file,
)

logger = get_logger(__name__)

DEFAULT_MIN_BODY_CHARS = 30
"""Production-quality default for `min_body_chars` when the pipeline / dispatch
layers call `split_into_sections`. The library function itself defaults to 0
so direct callers and existing tests see the original behavior unless they opt in."""


def split_into_sections(
    markdown: str,
    output_dir: Path,
    *,
    nested: bool = False,
    source_name: str = "markdown",
    min_level: int | None = None,
    images_dir: Path | None = None,
    min_body_chars: int = 0,
    frontmatter: str = "",
    provenance: dict[str, object] | None = None,
    doc_title: str | None = None,
    english_only: bool = False,
) -> list[Path]:
    """Split cleaned markdown into per-section files under `output_dir`.

    Default behavior (`min_level=None`): only numbered headings start sections
    (`# 1. ARCHITECTURE`, `## 1.4. ...`, `### 1.4.1. ...`). Best for docs with
    a numbered outline.

    `min_level=N`: any heading at depth ≥ N starts a section, numbered or not.
    Numbered ones still get `<number>. <title>.md` filenames; semantic ones
    use the heading text only (`Quick Start.md`).

    With `nested=True`, numbered sections land in numeric-prefix folders
    (`4/4.1/4.1.1. Title.md`); unnumbered sections land flat regardless.

    Sections whose body has fewer than `min_body_chars` non-whitespace chars
    are dropped (no file written, not listed in any parent's Subsections).
    This targets the case where an extractor promotes front-matter TOC entries
    to `# `-headings, producing empty "shell" sections whose actual content
    lives on later pages.

    Default `min_body_chars=0` preserves the original behavior for direct callers.
    `to_markdown()` and the pipeline `stitch()` opt into
    `DEFAULT_MIN_BODY_CHARS=30` to drop those empty shells.

    Always writes `INDEX.md` listing top-level sections.

    Args:
        markdown: The full markdown text to split.
        output_dir: Directory to write per-section files into. Created if missing.
        nested: If True, write numbered sections into nested numeric-prefix folders.
        source_name: Display name used in the `INDEX.md` heading.
        min_level: If set, also split on semantic headings at this depth or deeper.
        images_dir: Override the default `<output>/../images/` location.
        min_body_chars: Drop sections whose body has fewer than this many
            non-whitespace chars. Default 30. Set 0 to disable.
        frontmatter: Uniform provenance YAML block (from
            ``_provenance.build_provenance_frontmatter``) prepended above
            the heading of every written section file. Default "" = none.
            Ignored when ``provenance`` is given.
        provenance: Doc-level provenance fields (``source_type`` /
            ``source_label`` / ``source_file`` / ``doc_title``). When set,
            each section file gets RICH per-section frontmatter — the doc
            fields plus derived locators ``section_title`` / ``section_path``
            (ancestor breadcrumb) / ``section_number`` / ``heading_level``.
            Takes precedence over ``frontmatter``.
        doc_title: The document / manual title. When set, every section's
            in-file ``> ↑`` breadcrumb is rooted at ``[doc_title](INDEX.md)``,
            so each split chunk self-identifies its source document — including
            top-level sections, which otherwise get no breadcrumb. The in-chunk
            cross-contamination fix for a multi-manual RAG DB. None (default)
            keeps the legacy ancestor-only breadcrumb.

    Returns:
        The list of written section file paths (excluding `INDEX.md`).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = markdown.splitlines()
    sections = _parse_sections(lines, min_level=min_level)

    # Auto-fallback for non-numbered docs. When the caller passed no explicit
    # `min_level` and the numbered-only parse doesn't represent the doc's
    # top-level structure, re-parse at a detected min_level. Covers both the
    # zero-sections case (non-numbered manuals) and a few deep false-positive
    # numbered headings (e.g. a `#### 35 mm End Use` measurement heading)
    # producing a tiny spurious set while the real structure is non-numbered.
    if min_level is None and not _numbered_parse_is_representative(sections, lines):
        detected_level = _detect_fallback_min_level(lines)
        if detected_level is not None:
            reason = "no_numbered_headings" if not sections else "numbered_parse_misses_toplevel"
            logger.info(
                "split_auto_fallback_min_level level=%d reason=%s",
                detected_level,
                reason,
            )
            sections = _parse_sections(lines, min_level=detected_level)

    # Default: images live at `<output>/images/`, sibling to the sections/ dir.
    # That's what `to_markdown` produces. Callers with a different layout can
    # pass an explicit `images_dir`.
    if images_dir is None:
        images_dir = output_dir.parent / "images"

    # drop TOC-entry phantoms BEFORE empty-body / collision filters so
    # the count logs show the real-content section counts, not the bloat.
    # Marker promotes front-matter TOC / chapter-end summary list items into
    # `####`-shaped headings (`20.2. Foo, p. 596`); these duplicate the real
    # subsection content. See `is_toc_phantom_heading` for the detection rules.
    sections, toc_phantom_count = _drop_toc_phantom_sections(sections)
    if toc_phantom_count:
        logger.info("split_dropped_toc_phantom_sections count=%d", toc_phantom_count)

    # separate ancestor-only sections (parsed below min_level so
    # descendants can find their parent chain) from the writable list.
    # Ancestor-only sections render as plain-text in breadcrumbs via the
    # `kept_ids` mechanism — same pattern as chapter shells.
    ancestor_only_ids: set[int] = {id(s) for s in sections if s.is_ancestor_only}
    writable_sections = [s for s in sections if id(s) not in ancestor_only_ids]

    # Filter: drop empty-body shells, preserve chapter shells whose body is
    # empty but who have substantive descendants. Children lists are
    # filtered to kept-only so `## Subsections` doesn't link to dropped
    # files; parent refs are NOT re-anchored — the breadcrumb walker
    # uses `kept_ids` to render dropped intermediate ancestors as plain
    # text, preserving the chapter title in the chain.
    kept_ids: set[int] | None = None
    if min_body_chars > 0:
        kept, kept_ids = _select_kept_sections(writable_sections, min_body_chars=min_body_chars)
        dropped_count = len(writable_sections) - len(kept)
        if dropped_count:
            logger.info("split_dropped_empty_sections count=%d", dropped_count)
        _filter_children_to_kept(kept, kept_ids)
        writable_sections = kept
    elif ancestor_only_ids:
        # Even without min-body filtering, we need a kept_ids set so
        # breadcrumbs render ancestor-only entries as plain text rather
        # than as broken file links. kept_ids = every writable section.
        kept_ids = {id(s) for s in writable_sections}

    # Opt-in English-only: drop sections belonging to a non-English
    # top-level subtree — a multilingual manual's translated branch. Judged by
    # the WHOLE subtree's aggregated text (via `_filter_english_subtrees`), not
    # per-leaf, so a translation fragmented into terse sections is still caught.
    # OFF by default. The kept set shrinks to the English branches; a dropped
    # non-English ancestor of a surviving section renders as plain text, same as
    # the empty-shell path.
    if english_only:
        english, non_english = _filter_english_subtrees(sections, writable_sections)
        if non_english:
            logger.info("split_dropped_non_english_sections count=%d", non_english)
        kept_ids = {id(s) for s in english}
        _filter_children_to_kept(english, kept_ids)
        writable_sections = english

    # `sections` from here on means the writable set. Use a local rebinding
    # so the rest of the function (path collisions, slug map, INDEX, etc.)
    # operates on the writable list and never tries to render ancestor-only
    # sections to disk.
    sections = writable_sections

    sections, path_collisions = _dedupe_section_paths(sections, output_dir, nested=nested)
    for c in path_collisions:
        logger.info(
            "split_dropped_filename_collision path=%s kept=%r kept_body_chars=%d "
            "dropped=%r dropped_body_chars=%d",
            c.target_path.name,
            c.kept_title,
            c.kept_body_chars,
            c.dropped_title,
            c.dropped_body_chars,
        )
    if path_collisions:
        logger.info("split_dropped_filename_collisions count=%d", len(path_collisions))

    # slug -> ALL sections with that heading slug (document order). A slug is
    # ambiguous when repeated (every plugin module has a "Module Header"); the
    # rewriter resolves each ref to the NEAREST candidate, so this MUST keep
    # every section, not collapse to a last-wins single value.
    slug_to_sections: dict[str, list[_Section]] = {}
    for s in sections:
        slug = heading_slug(s.heading_line)
        if slug:
            slug_to_sections.setdefault(slug, []).append(s)

    written: list[Path] = [
        _write_section_file(
            section,
            output_dir,
            nested=nested,
            slug_to_sections=slug_to_sections,
            images_dir=images_dir,
            kept_ids=kept_ids,
            frontmatter=frontmatter,
            provenance=provenance,
            doc_title=doc_title,
        )
        for section in sections
    ]

    index_path = _write_index(
        sections, output_dir, nested=nested, source_name=source_name, kept_ids=kept_ids
    )

    # Clean stale .md files left over from previous runs (e.g. an earlier
    # stitch wrote a section that's now filtered out by min_body_chars). Keep
    # the just-written set + INDEX. Empty subdirs from nested mode are pruned.
    keep: set[Path] = {p.resolve() for p in written}
    keep.add(index_path.resolve())
    for stale in output_dir.rglob("*.md"):
        if stale.resolve() not in keep:
            stale.unlink()
            logger.info("split_removed_stale_section path=%s", stale)
    for sub in sorted(
        (p for p in output_dir.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        # Directory wasn't empty (still holds non-md files we shouldn't touch).
        with contextlib.suppress(OSError):
            sub.rmdir()

    return written
