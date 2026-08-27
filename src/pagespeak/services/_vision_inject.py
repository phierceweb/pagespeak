"""Markdown-injection half of the vision pass.

Pure text transforms — no LLM, no I/O: rewrite each matching image ref
with its enriched caption + Mermaid block (`inject_diagrams`), and build
the alt-text map that feeds the alt-aware prompt (`alt_text_by_basename`).
`_diagrams.py` owns the per-pass orchestration and re-exports every name
here, so the public + test surface is unchanged.
"""

from __future__ import annotations

from ..models._models import Diagram
from ._image_refs import ImageRef, parse_image_refs, replace_image_refs


def alt_text_by_basename(markdown: str) -> dict[str, str]:
    """Map each markdown image ref's basename → its existing alt text.

    Feeds the figure's source description into the alt-text-aware vision
    prompt. First occurrence wins (mirrors `inject_diagrams`'s basename
    matching). The alt is returned verbatim; the prompt renderer trims it.
    """
    out: dict[str, str] = {}
    for ref in parse_image_refs(markdown):
        out.setdefault(ref.target.rsplit("/", 1)[-1], ref.alt)
    return out


def inject_diagrams(
    markdown: str, diagrams: dict[str, Diagram], *, preserve_alt: bool = False
) -> str:
    """Pure markdown transform. For each `![...](path)` whose basename
    matches a `Diagram` in `diagrams`, inject a caption (alt text) and
    a Mermaid block (if non-null) below the image ref. Refs without a
    matching diagram are left unchanged.

    Public re-export of the internal `_inject_diagrams` so the
    gather/assemble split has named handles for both halves of the
    vision pass. ``preserve_alt`` (faithful mode) keeps each image's
    existing alt verbatim and only appends Mermaid — see `_inject_diagrams`.
    """
    return _inject_diagrams(markdown, diagrams, preserve_alt=preserve_alt)


def _escape_alt(text: str) -> str:
    """Make a caption string safe to drop into a markdown image's alt slot.

    Markdown alt text can't contain unescaped `[` or `]` (breaks the syntax)
    or newlines (breaks the image ref). Replace defensively.
    """
    return text.replace("[", "(").replace("]", ")").replace("\n", " ").strip()


def _inject_diagrams(
    markdown: str, diagrams: dict[str, Diagram], *, preserve_alt: bool = False
) -> str:
    """Rewrite each `![...](path)` whose basename matches a `Diagram`:

    - Caption goes into the image's alt text (structurally extractable).
    - Mermaid block (if any) is appended below, tagged with
      `pagespeak-image="<path>"` in the fenced-block info string so
      consumers can pair the Mermaid with its source image.

    Refs whose basename has no matching `Diagram` are left unchanged.

    With ``preserve_alt`` (faithful mode), the image's existing alt is kept
    **verbatim** — the enriched caption is NOT injected — and only the Mermaid
    block is appended (for diagrams). A non-diagram figure is left untouched.
    Use this to add structure without modifying a publisher's source alt text.
    """

    def repl(image: ImageRef) -> str | None:
        path = image.target
        diagram = diagrams.get(path.rsplit("/", 1)[-1])
        if not diagram:
            return None
        # Faithful mode keeps the source alt verbatim and only appends Mermaid;
        # otherwise the enriched caption replaces the alt.
        original = markdown[image.span[0] : image.span[1]]
        ref = original if preserve_alt else f"![{_escape_alt(diagram.caption)}]({path})"
        if diagram.mermaid:
            return f'{ref}\n\n```mermaid pagespeak-image="{path}"\n{diagram.mermaid}\n```'
        return ref

    return replace_image_refs(markdown, repl)[0]


__all__ = ["alt_text_by_basename", "inject_diagrams"]
