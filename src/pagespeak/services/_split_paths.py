"""Where the splitter writes each section: filename slugs and nested folders.

Imports `_Section` from `_split_parse`; `_split_write` and `_split_filter`
call here.
"""

from __future__ import annotations

from pathlib import Path

from ._split_identity import _strip_embedded_links
from ._split_parse import _Section

_MAX_FILENAME_LEN = 200


def _handelize_stem(name: str) -> str:
    """Lowercase, path-safe slug of a name — a *fixed point* of QMD's ``handelize``.

    Mirrors qmd's ``handelize`` (store.js) on one path segment — collapse every
    run of non-(unicode letter/number/``$``) to a single ``-``, trim edge dashes,
    keep unicode letters — and additionally lowercases. Lowercasing stays
    idempotent under ``handelize`` (which never touches case) while making the
    slug portable to any consumer that lowercases, and collision-safe on
    case-insensitive filesystems. The upshot: a filename pagespeak writes equals
    the key QMD indexes it under, so an in-doc breadcrumb link *is* a valid
    ``qmd get`` path. Idempotency vs. qmd's real output is pinned by test_split.
    """
    out: list[str] = []
    prev_dash = False
    for ch in name.lower():
        if ch.isalnum() or ch == "$":
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")


def _sanitize_filename(name: str) -> str:
    """Sanitize a section's display name into a slugified `.md` filename.

    Strips embedded markdown links, then slugs via `_handelize_stem` (a fixed
    point of QMD `handelize`) and truncates to `_MAX_FILENAME_LEN`. A name with
    no slug-able content (`## #`, `## ·`) falls back to a generic `section`
    stem; the post-pass collision resolver (`_resolve_filename_collisions`)
    assigns numeric `-2`, `-3` suffixes to distinct sections that slug to the
    same name, case-only variants included.
    """
    stem = _handelize_stem(_strip_embedded_links(name))
    if not stem:
        stem = "section"
    if len(stem) > _MAX_FILENAME_LEN:
        stem = stem[:_MAX_FILENAME_LEN].strip("-")
    return f"{stem}.md"


def _semantic_folder_name(section: _Section) -> str:
    """Folder identifier for a semantic (unnumbered) section.

    Sanitized heading title, with the `.md` suffix that
    `_sanitize_filename` always appends stripped off.
    """
    return _sanitize_filename(section.title).removesuffix(".md")


def _folder_component(section: _Section) -> str:
    """Folder name an ancestor contributes to a nested path.

    A numbered ancestor contributes its (cumulative) number string
    (`1.1.1`), matching the numeric-folder scheme — so a semantic descendant
    nests in the numeric tree. A semantic ancestor contributes its title
    slug. This is what keeps an unnumbered subsection of a numbered section
    under `1/1.1/1.1.1/` instead of a divergent title-named path.
    """
    if section.number is not None:
        return _handelize_stem(section.number)
    return _semantic_folder_name(section)


def _nested_relative_dir(section: _Section) -> Path:
    """Folder path for a section in nested mode.

    Numbered sections derive the folder from the number string directly
    (`1.` -> `1/`, `1.1.` -> `1/`, `1.1.1.` -> `1/1.1/`). This keeps the
    numbered-section layout stable even when intermediate ancestor sections are
    missing from the doc (e.g. a `## 1.4. Foo` that has no `# 1.` parent).

    Semantic sections walk the actual parent chain (numbered ancestors
    contribute their number, semantic contribute their title slug). Top-level
    semantic sections land in their own title-named folder; deeper ones nest
    by ancestor.
    """
    if section.number is not None:
        parts = section.number.split(".")
        if len(parts) <= 1:
            return Path(_handelize_stem(parts[0]))
        chain = [parts[0]]
        for i in range(2, len(parts)):
            chain.append(".".join(parts[:i]))
        return Path(*[_handelize_stem(c) for c in chain])

    chain_sections: list[_Section] = []
    node: _Section | None = section
    while node is not None:
        chain_sections.append(node)
        node = node.parent
    chain_sections.reverse()  # [root, ..., section]

    ancestors = chain_sections[:-1]
    if not ancestors:
        # Top-level semantic section: its own title-named folder.
        return Path(_semantic_folder_name(section))
    # Each ancestor contributes its number (when numbered) or title slug, so a
    # semantic section under a numbered ancestor nests in the numeric tree
    # (1/1.1/1.1.1/Namespaces.md) instead of diverging into a title path.
    return Path(*[_folder_component(a) for a in ancestors])


def _section_output_path(section: _Section, output_dir: Path, *, nested: bool) -> Path:
    filename = _sanitize_filename(section.display_name)
    if section.filename_suffix:
        # Insert "-2"/"-3"/etc. before the `.md` extension when the
        # collision resolver has assigned a disambiguator.
        stem, ext = filename.rsplit(".", 1)
        filename = f"{stem}{section.filename_suffix}.{ext}"
    if not nested:
        return output_dir / filename
    return output_dir / _nested_relative_dir(section) / filename
