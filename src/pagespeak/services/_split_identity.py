"""Per-section identity frontmatter for the splitter.

Builds the YAML block every split section file leads with: always-on
structural identity (`doc_id` / `section_id` / `parent_id` / locators /
`order`) merged with the opt-in doc-level source provenance fields.
`_split_write` computes the join keys (paths) and calls in here.
"""

from __future__ import annotations

import re

from ._provenance import build_frontmatter
from ._split_parse import _Section

_EMBEDDED_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _strip_embedded_links(name: str) -> str:
    """`a[b](c)d` → `abd`. Idempotent."""
    prev = None
    while prev != name:
        prev = name
        name = _EMBEDDED_MD_LINK.sub(r"\1", name)
    return name


def _section_path(section: _Section) -> list[str]:
    """Ancestor heading titles, root-first — this section's breadcrumb path.

    Powers the `section_path` frontmatter field (the high-ROI RAG locator: a
    retrieved chunk knows where it sits in the document). Uses `display_name`
    (number + title) to match the on-page breadcrumb, with embedded markdown
    links stripped."""
    crumbs: list[str] = []
    cursor = section.parent
    while cursor is not None:
        crumbs.append(_strip_embedded_links(cursor.display_name))
        cursor = cursor.parent
    crumbs.reverse()
    return crumbs


def _section_frontmatter(
    section: _Section,
    provenance: dict[str, object] | None,
    *,
    doc_id: str,
    doc_title: str | None,
    section_id: str,
    parent_id: str | None,
    order: int,
    source_id: str | None = None,
    source_sha256: str | None = None,
) -> str:
    """Per-section frontmatter: always-on structural identity plus opt-in
    source provenance.

    Structural fields (every section, every run): `doc_id`, `section_id`
    (the section's own relative path — the stable join key), `parent_id`
    (nearest written ancestor), `section_title`, `section_path` (ancestor
    breadcrumb), `section_number`, `heading_level`, `depth`, `order`
    (1-based document order); plus `source_id` / `source_sha256` (which
    source work, which exact bytes) whenever the caller can resolve them.
    Source tags (`source_type` / `source_label` / `source_file`) appear only
    when the caller supplies `provenance`; a provenance-supplied `doc_title`
    wins over the `doc_title` param.
    """
    fields: dict[str, object] = dict(provenance) if provenance else {}
    if fields.get("doc_title") is None:
        fields["doc_title"] = doc_title
    fields["doc_id"] = doc_id
    fields["source_id"] = source_id
    fields["source_sha256"] = source_sha256
    fields["section_id"] = section_id
    fields["parent_id"] = parent_id
    fields["section_title"] = _strip_embedded_links(section.title)
    path = _section_path(section)
    fields["section_path"] = path or None
    fields["section_number"] = section.number or None
    fields["heading_level"] = section.level
    fields["depth"] = len(path)
    fields["order"] = order
    fields["part_index"] = section.part_index
    fields["part_count"] = section.part_count
    return build_frontmatter(fields)
