"""Section file/path construction + writing for the splitter.

Filename sanitization, nested-folder path building, image + in-doc-ref
rewriting, breadcrumbs, and the `_write_section_file` / `_write_index`
writers. Per-section identity frontmatter lives in `_split_identity`.
`_split` re-exports `_build_breadcrumb`. Imports `_Section` +
`_is_page_anchor_line` from `_split_parse`; the orchestrator + filter
call here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ._split_identity import _section_frontmatter, _strip_embedded_links
from ._split_parse import _is_page_anchor_line, _Section

IN_DOC_REF_RE = re.compile(r"\[([^\]]+)\]\(#([^)]+)\)")

IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

_MAX_FILENAME_LEN = 200


def _sanitize_filename(name: str) -> str:
    """Sanitize a section's display name into a `.md` filename.

    Strips embedded markdown links, replaces FS-illegal + markdown-link-
    breaking chars (`| [ ]`), collapses whitespace runs, and truncates to
    `_MAX_FILENAME_LEN` (255-byte FS
    limit headroom). Truncation is plain — no hash suffix is appended.
    Collisions between two distinct truncated names are resolved by the
    post-pass collision resolver (`_resolve_filename_collisions`),
    which assigns numeric `-2`, `-3` suffixes in document order.
    """
    name = _strip_embedded_links(name)
    name = name.replace("/", " - ").replace("\\", " - ")
    name = name.replace(":", " -")
    name = name.replace("*", "")
    name = name.replace("?", "")
    name = name.replace('"', "")
    name = name.replace("<", "(").replace(">", ")")
    # `|` breaks a downstream markdown table; `[` `]` break a link target — so a
    # section-title-derived filename is safe when used as a breadcrumb link
    # target too (a multilingual manual's `… | Wireless Monitor Set` case).
    name = name.replace("[", "(").replace("]", ")")
    name = name.replace("|", " ")
    name = re.sub(r"\s{2,}", " ", name).strip()
    # A degenerate heading (`## #`, `## ·`) leaves a stem with no word content —
    # `#.md`, which downstream indexers (QMD `handelize`) reject as "no valid
    # filename content". Fall back to a generic stem; the collision resolver
    # disambiguates multiples. `\w` is Unicode-aware, so legitimate CJK /
    # Cyrillic section names (real word content) are preserved.
    if not re.search(r"\w", name):
        name = "section"
    if len(name) > _MAX_FILENAME_LEN:
        name = name[:_MAX_FILENAME_LEN].rstrip()
    return f"{name}.md"


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
        return section.number
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
            return Path(parts[0])
        chain = [parts[0]]
        for i in range(2, len(parts)):
            chain.append(".".join(parts[:i]))
        return Path(*chain)

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


def _rewrite_image_paths_relative(
    text: str,
    section_file: Path,
    images_dir: Path,
) -> str:
    """Rewrite `![alt](images/foo.png)` to a relative path from `section_file`.

    pagespeak's standard layout puts images at `<output>/images/` and section
    files under `<output>/sections/[nested]/<file>.md`. From a section file,
    the right path is `../../../images/foo.png` etc. — depth depends on the
    nested layout. Computed via `os.path.relpath`.
    """
    section_dir = section_file.parent

    def _replace(match: re.Match[str]) -> str:
        alt, path = match.group(1), match.group(2)
        if not path.startswith(("images/", "images\\")):
            return match.group(0)
        basename = Path(path).name
        target = images_dir / basename
        rel = os.path.relpath(target, section_dir).replace(os.sep, "/")
        return f"![{alt}]({rel})"

    return IMAGE_REF_RE.sub(_replace, text)


def _nearest_section(candidates: list[_Section], from_section: _Section) -> _Section:
    """Of several same-slug sections, the one NEAREST `from_section` in the tree.

    Nearest = deepest lowest-common-ancestor (a sibling beats a cousin beats an
    unrelated section). Ties and the no-common-ancestor case break by document
    order — `min` is stable and `candidates` is in document order. This is what
    keeps a Clarity-module ref to `#module-header` pointing at Clarity's own
    header rather than the last same-named section in the document.
    """
    if len(candidates) == 1:
        return candidates[0]
    # from_section's ancestor chain (self → root) → distance from self.
    from_depth: dict[int, int] = {}
    cur: _Section | None = from_section
    d = 0
    while cur is not None:
        from_depth[id(cur)] = d
        cur = cur.parent
        d += 1

    def lca_distance(cand: _Section) -> int:
        c: _Section | None = cand
        while c is not None:
            hit = from_depth.get(id(c))
            if hit is not None:
                return hit
            c = c.parent
        return 1 << 30  # no common ancestor

    return min(candidates, key=lca_distance)


def _rewrite_in_doc_refs_to_section_files(
    text: str,
    from_section: _Section,
    slug_to_sections: dict[str, list[_Section]],
    output_dir: Path,
    *,
    nested: bool,
) -> str:
    """Rewrite `[label](#slug)` -> `[label](relative/path/to/Section.md)`.

    Only touches refs whose anchor matches a known section's heading slug.
    Refs to unknown anchors (subsection-level slugs, real `#real-anchor` links,
    URLs) are preserved. When a slug is AMBIGUOUS (a repeated heading — every
    plugin module has a "Module Header"), the ref resolves to the section
    NEAREST `from_section`, not an arbitrary collision winner.
    """
    from_path = _section_output_path(from_section, output_dir, nested=nested)

    def _replace(m: re.Match[str]) -> str:
        label, slug = m.group(1), m.group(2)
        candidates = slug_to_sections.get(slug)
        if not candidates:
            return m.group(0)
        target = _nearest_section(candidates, from_section)
        target_path = _section_output_path(target, output_dir, nested=nested)
        rel = os.path.relpath(target_path, from_path.parent).replace(os.sep, "/")
        return _md_link(label, rel)

    return IN_DOC_REF_RE.sub(_replace, text)


_CRUMB_MAX_CHARS = 50
# Markdown-structural / escape chars that must never reach a `> ↑ [crumb](…)`
# line: pipes break a downstream table, brackets/parens break the link itself,
# backslashes + control whitespace are noise.
_BREADCRUMB_UNSAFE_RE = re.compile(r"[|\[\]()<>\\\n\r\t]+")


def _sanitize_crumb(name: str) -> str:
    """Make ANY breadcrumb crumb label (root or ancestor) SAFE + bounded.

    Every crumb is interpolated into a `> ↑ [<label>](…)` link, so markdown-
    structural chars are stripped (→ space), whitespace collapsed, and the
    result capped at `_CRUMB_MAX_CHARS` with an ellipsis. The label can be a
    filename-derived doc title (a long-titled reference doc's name) OR an
    ancestor *section* title carrying pipes (a multilingual manual case:
    `ew IEM G4 | Wireless Monitor Set`); this guarantees neither breaks markdown
    nor bloats every breadcrumb. May return "" on all-breaker input — callers
    substitute a placeholder. QUALITY (casing, brand names, cruft) is the
    caller's job via an explicit `source_label`; this only guarantees safety.
    """
    cleaned = re.sub(r"\s+", " ", _BREADCRUMB_UNSAFE_RE.sub(" ", name)).strip()
    if len(cleaned) > _CRUMB_MAX_CHARS:
        cleaned = cleaned[:_CRUMB_MAX_CHARS].rstrip() + "…"
    return cleaned


def _md_link(label: str, target: str) -> str:
    """`[label](target)`, angle-wrapping the target when it contains a space or
    paren.

    An unescaped space in a markdown link destination BREAKS the link:
    CommonMark stops the destination at the first space, so `[x](a b.md)`
    renders as literal text, not a link (verified with markdown_it). Section
    filenames are human-readable and keep their spaces, so nearly every
    generated nav link needs this. Angle brackets let the destination hold
    spaces — `[x](<a b.md>)` is a valid link. Targets are pre-sanitized of
    `< >` (see `_sanitize_filename`), so the wrapper itself can't be broken.
    """
    if " " in target or "(" in target or ")" in target:
        return f"[{label}](<{target}>)"
    return f"[{label}]({target})"


def _build_breadcrumb(
    section: _Section,
    output_dir: Path,
    section_path: Path,
    *,
    nested: bool,
    kept_ids: set[int] | None = None,
    doc_title: str | None = None,
) -> str | None:
    """Build a `> ↑ [Doc](INDEX.md) / [Root](...) / [Parent](...)` breadcrumb
    line. Returns None only when there's nothing to show (no `doc_title` AND
    no parent — a root section in the legacy, title-less mode).

    Walks `section.parent` up to the root, building an entry per ancestor,
    joined root-first. Ancestors in `kept_ids` (actually written to disk)
    render as `[Title](rel-link)`; filtered-out ancestors render as plain
    text so an LLM reading one chunk still sees the chapter title in the
    chain. When `kept_ids` is None, every ancestor renders as a link.

    `doc_title`: when set, the breadcrumb is rooted at
    `[doc_title](INDEX.md)` — the manual/document title linking to the
    section index — so EVERY section file (including top-level ones, which
    otherwise get no breadcrumb) carries its source-document identity. This
    is the in-chunk cross-contamination fix for a multi-manual RAG DB.
    Skipped for the doc-title section itself (it would point at its own
    listing).
    """
    crumbs: list[str] = []
    if doc_title:
        stripped = _strip_embedded_links(doc_title)
        # Skip the doc-title section itself (it would link to its own listing).
        if stripped != _strip_embedded_links(section.display_name):
            root = _sanitize_crumb(stripped)
            if root:
                index_rel = os.path.relpath(output_dir / "INDEX.md", section_path.parent).replace(
                    os.sep, "/"
                )
                crumbs.append(_md_link(root, index_rel))

    ancestor_crumbs: list[str] = []
    cursor: _Section | None = section.parent
    while cursor is not None:
        # Sanitize the ancestor label the same way as the root crumb: strip
        # embedded markdown links (a title `[Foo](#anchor)` would nest links and
        # break the breadcrumb's own `[...](...)`) AND strip markdown-breakers +
        # cap length — a section title can carry a pipe (a multilingual manual's
        # `ew IEM G4 | Wireless Monitor Set` chapter heading) that would corrupt
        # a downstream table. Empty result → a placeholder, never a broken `[]`.
        display = _sanitize_crumb(_strip_embedded_links(cursor.display_name)) or "…"
        if kept_ids is None or id(cursor) in kept_ids:
            ancestor_path = _section_output_path(cursor, output_dir, nested=nested)
            rel = os.path.relpath(ancestor_path, section_path.parent).replace(os.sep, "/")
            ancestor_crumbs.append(_md_link(display, rel))
        else:
            ancestor_crumbs.append(display)
        cursor = cursor.parent
    ancestor_crumbs.reverse()
    crumbs.extend(ancestor_crumbs)

    if not crumbs:
        return None
    return "> ↑ " + " / ".join(crumbs)


def _written_parent_id(
    section: _Section, output_dir: Path, *, nested: bool, kept_ids: set[int] | None
) -> str | None:
    """`section_id` of the nearest ancestor actually written to disk, or None.

    Ancestor-only / filtered-out ancestors are skipped (`kept_ids`), so the
    emitted `parent_id` is always a joinable key to an existing section file.
    """
    cursor = section.parent
    while cursor is not None:
        if kept_ids is None or id(cursor) in kept_ids:
            path = _section_output_path(cursor, output_dir, nested=nested)
            return path.relative_to(output_dir).as_posix()
        cursor = cursor.parent
    return None


def _write_section_file(
    section: _Section,
    output_dir: Path,
    *,
    nested: bool,
    doc_id: str,
    order: int,
    slug_to_sections: dict[str, list[_Section]] | None = None,
    images_dir: Path | None = None,
    kept_ids: set[int] | None = None,
    provenance: dict[str, object] | None = None,
    doc_title: str | None = None,
) -> Path:
    path = _section_output_path(section, output_dir, nested=nested)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [section.heading_line]
    # preserved `<span id="page-X-Y"></span>` lines follow the
    # heading in cleaned MD with no blank between. Mirror that layout in
    # section files instead of inserting an extra blank after the heading.
    content = list(section.content_lines)
    while content and _is_page_anchor_line(content[0]):
        lines.append(content.pop(0))
    lines.append("")

    breadcrumb = _build_breadcrumb(
        section, output_dir, path, nested=nested, kept_ids=kept_ids, doc_title=doc_title
    )
    if breadcrumb:
        lines.append(breadcrumb)
        lines.append("")

    body = "\n".join(content).strip()
    if body:
        if slug_to_sections:
            body = _rewrite_in_doc_refs_to_section_files(
                body, section, slug_to_sections, output_dir, nested=nested
            )
        if images_dir is not None:
            body = _rewrite_image_paths_relative(body, path, images_dir)
        lines.append(body)
        lines.append("")

    if section.children:
        lines.append("## Subsections")
        lines.append("")
        for child in section.children:
            child_path = _section_output_path(child, output_dir, nested=nested)
            rel = os.path.relpath(child_path, path.parent).replace(os.sep, "/")
            # Strip embedded markdown links from the display text — without
            # this, a child titled `[Foo](#anchor)` would emit a nested
            # `[label[Foo](#anchor)bar](rel.md)` that breaks the bullet's
            # own markdown link syntax.
            display = _strip_embedded_links(child.display_name)
            lines.append(f"- {_md_link(display, rel)}")
        lines.append("")

    # Identity frontmatter sits above the heading so every section file leads
    # with its joinable keys (doc_id / section_id / parent_id) + locators.
    front = _section_frontmatter(
        section,
        provenance,
        doc_id=doc_id,
        doc_title=doc_title,
        section_id=path.relative_to(output_dir).as_posix(),
        parent_id=_written_parent_id(section, output_dir, nested=nested, kept_ids=kept_ids),
        order=order,
    )
    path.write_text(front + "\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _write_index(
    sections: list[_Section],
    output_dir: Path,
    *,
    nested: bool,
    source_name: str,
    kept_ids: set[int] | None = None,
) -> Path:
    index_path = output_dir / "INDEX.md"
    # "Top-level" = sections with no kept ancestor in the parent chain.
    # A kept section whose parent points to a dropped chapter shell still
    # has no kept ancestor and belongs at top-level. When kept_ids is None
    # (no body-filter ran), fall back to literal `parent is None`.
    if kept_ids is None:
        top_level = [s for s in sections if s.parent is None]
    else:
        top_level = [s for s in sections if _effective_top_level(s, kept_ids)]
    lines = [f"# Split Sections: {source_name}", ""]
    if top_level:
        lines.append("## Top-level Sections")
        lines.append("")
        for section in top_level:
            file_path = _section_output_path(section, output_dir, nested=nested)
            rel = file_path.relative_to(output_dir).as_posix()
            # Strip embedded links from the label (consistency with breadcrumb /
            # Subsections) AND angle-wrap the space-containing target.
            lines.append(f"- {_md_link(_strip_embedded_links(section.display_name), rel)}")
        lines.append("")
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return index_path


def _effective_top_level(section: _Section, kept_ids: set[int]) -> bool:
    """True if no ancestor of `section` is in `kept_ids`.

    With dropped intermediates allowed in the parent chain (see
    `_filter_children_to_kept`), a section whose `parent` is non-None
    but points to a dropped section has no kept ancestor — it should
    appear as top-level in INDEX.
    """
    cursor = section.parent
    while cursor is not None:
        if id(cursor) in kept_ids:
            return False
        cursor = cursor.parent
    return True
