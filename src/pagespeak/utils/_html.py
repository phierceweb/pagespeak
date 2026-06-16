"""Inline-HTML-fragment → markdown.

A small, reusable cleaner for the messy inline HTML that turns up embedded
in structured sources (Canvas QTI question stems, instructions blocks).
Callers hand in an HTML *fragment* string and get back clean markdown.

The value over calling markdownify directly is the sanitize pass that
markdownify does not do: dropping hidden tracking elements, demoting HTML
headings to bold (so an embedded fragment never introduces ATX `#`
headings that would fool a document splitter), flattening `<sub>`/`<sup>`
to inline text for RAG searchability, and special-casing the two
*meaningful* embeds — Canvas equation-images (which carry their LaTeX) and
media-token `<img>` tags (resolved to a local path via a caller hook).

It is a utility callers opt into; it is intentionally NOT wired into the
existing DOCX / MarkItDown paths.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from markdownify import markdownify

_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _latex_from_alt(alt: str) -> str:
    """Canvas equation images carry `alt="LaTeX: <expr>"`. Pull `<expr>`."""
    prefix = "LaTeX:"
    return alt[len(prefix) :].strip() if alt.startswith(prefix) else ""


def _attr(tag: Tag, name: str) -> str:
    """Read a tag attribute as a plain string ('' if absent/multi-valued).

    BeautifulSoup types attribute reads as `str | list[str] | None`; this
    narrows to the single-string case these callers want.
    """
    value = tag.get(name)
    return value if isinstance(value, str) else ""


def html_fragment_to_markdown(
    html: str,
    *,
    media_resolver: Callable[[str], str] | None = None,
    equation_to_latex: bool = True,
) -> str:
    """Clean an inline HTML fragment into markdown.

    Args:
        html: An HTML fragment (may be empty / whitespace-only).
        media_resolver: Optional `src -> local_path` hook for `<img>` tags.
            Returns the local path to link, or an empty string to drop the
            image and keep only its alt text. When None, `<img>` tags are
            left untouched for markdownify to convert.
        equation_to_latex: When True (default), `<img class="equation_image">`
            is replaced by inline `$<latex>$` from its `data-equation-content`
            (or `alt="LaTeX: ..."`).

    Returns:
        Clean markdown. Empty string for empty/whitespace-only input.
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Drop non-content and hidden (e.g. Proctorio display:none tracking spans).
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(style=True):
        if "display:none" in _attr(tag, "style").replace(" ", "").lower():
            tag.decompose()

    # Images: equation → inline LaTeX; media → resolved local path or alt text.
    for img in list(soup.find_all("img")):
        raw_classes = img.get("class")
        classes = raw_classes if isinstance(raw_classes, list) else []
        if equation_to_latex and "equation_image" in classes:
            latex = _attr(img, "data-equation-content") or _latex_from_alt(_attr(img, "alt"))
            img.replace_with(NavigableString(f"${latex}$" if latex else ""))
            continue
        if media_resolver is not None:
            resolved = media_resolver(_attr(img, "src"))
            if resolved:
                img["src"] = resolved
            else:
                img.replace_with(NavigableString(_attr(img, "alt")))

    # Demote HTML headings to bold — an inline fragment's heading is
    # sub-emphasis, not a document section; emitting `#` would fool a splitter.
    for h in soup.find_all(_HEADING_TAGS):
        text = h.get_text(strip=True)
        h.name = "p"
        h.clear()
        if text:
            strong = soup.new_tag("strong")
            strong.string = text
            h.append(strong)

    # Flatten sub/sup to inline text (CO<sub>2</sub> -> CO2) for searchability.
    for tag in soup.find_all(["sub", "sup"]):
        tag.unwrap()

    # Unwrap emphasis nested inside the SAME emphasis kind — Canvas nests
    # <strong><b>…</b></strong>, which markdownify renders as `****word****`
    # (shattered emphasis). <em><strong>…</strong></em> (bold-italic) is a
    # different kind and stays.
    for tag in soup.find_all(["strong", "b"]):
        if tag.find_parent(["strong", "b"]) is not None:
            tag.unwrap()
    for tag in soup.find_all(["em", "i"]):
        if tag.find_parent(["em", "i"]) is not None:
            tag.unwrap()

    md = markdownify(
        str(soup),
        escape_asterisks=False,
        escape_underscores=False,
        escape_misc=False,
    )
    return _BLANK_RUN_RE.sub("\n\n", md).strip()
