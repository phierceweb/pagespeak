from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from pf_core.log import get_logger

from ..models._models import IngestResult
from ..utils._mathml import prepare_mathml_for_markdown, restore_math

logger = get_logger(__name__)

_OFFICE_MEDIA_PREFIXES = ("word/media/", "ppt/media/", "xl/media/")

# EPUB images live at arbitrary in-zip paths (OPS/images/, images/,
# OEBPS/images/, …) rather than a fixed office `*/media/` prefix, so we
# extract by image extension instead of by prefix.
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")

# Captures the three pieces of a markdown image ref so the path (group 2)
# can be retargeted while alt text and surrounding syntax are preserved.
_MD_IMAGE_REF_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")

# MarkItDown discards DOCX inline-image payloads and emits a dead
# truncated stub `![](data:image/png;base64...)` that points nowhere.
# Whole-line only — adjacent `Figure N.` captions are separate lines and
# are preserved. Inline-within-prose data URIs are deliberately out of
# scope.
_DEAD_DATA_URI_IMG_RE = re.compile(r"^\s*!\[[^\]]*\]\(\s*data:[^)]*\)\s*$")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _strip_dead_data_uri_images(md: str) -> str:
    """Drop whole-line dead `data:` image stubs; collapse the resulting
    blank-line runs. Real `![](images/..)` refs are untouched."""
    kept = [ln for ln in md.splitlines() if not _DEAD_DATA_URI_IMG_RE.match(ln)]
    out = "\n".join(kept)
    out = _BLANK_RUN_RE.sub("\n\n", out)
    if md.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out


def _convert_html_string(converter: Any, html: str) -> Any:
    """Convert an in-memory HTML string via markitdown (which reads files) by
    routing it through a temp ``.html`` file so the format is detected."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        return converter.convert(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _run_markitdown(converter: Any, path: Path) -> str:
    """Run markitdown on `path`, pre-resolving MathML to ``$LaTeX$`` for HTML
    inputs — markitdown otherwise double-renders the parallel
    presentation+content MathML and flattens superscripts. The math is swapped
    for escape-proof placeholder tokens before conversion and restored after,
    so markitdown never sees (and can't mangle) it."""
    math_map: dict[str, str] = {}
    if path.suffix.lower() in (".html", ".htm"):
        html = path.read_text(encoding="utf-8", errors="replace")
        tokenized, math_map = prepare_mathml_for_markdown(html)
        result = (
            _convert_html_string(converter, tokenized) if math_map else converter.convert(str(path))
        )
    else:
        result = converter.convert(str(path))
    text = result.text_content or ""
    if math_map:
        text = restore_math(text, math_map)
    return _strip_dead_data_uri_images(text)


def convert_with_markitdown(
    path: Path,
    *,
    output_dir: Path | None = None,
    html_base_url: str | None = None,
) -> IngestResult:
    """Convert a non-PDF document via MarkItDown; extract embedded images
    directly from the office-format zip container if present.

    HTML inputs first have their parallel presentation+content MathML resolved
    to ``$LaTeX$`` (see :func:`_run_markitdown`), which markitdown would
    otherwise double-render and flatten. Frontmatter stripping
    (`strip_frontmatter`) moved to `services._frontmatter` and runs in Phase 3
    of `to_markdown()`.
    """
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise ImportError(
            "Non-PDF formats require markitdown. Install with: pip install markitdown"
        ) from e

    md = MarkItDown()
    markdown_text = _run_markitdown(md, path)

    saved_images: list[Path] = []
    if output_dir is not None:
        suffix = path.suffix.lower()
        if suffix == ".epub":
            # EPUB: MarkItDown emits real `![](../images/..)` refs but never
            # extracts the embedded binaries, so the vision pass saw zero
            # images. Pull them out of the zip, then retarget the refs to
            # `images/<name>` so they resolve next to the .md.
            saved_images = _extract_epub_media(path, output_dir)
            markdown_text = _retarget_image_refs(markdown_text, saved_images)
        elif suffix in (".html", ".htm"):
            # HTML: MarkItDown keeps `<img>` tags as remote `http(s)://` refs
            # and never downloads them, so the vision pass saw zero images.
            # Pull each one local + retarget the ref (on by default; gated by
            # PAGESPEAK_DOWNLOAD_REMOTE_IMAGES). Mirrors the EPUB fix above.
            from ._remote_images import (
                download_remote_images,
                download_remote_images_enabled,
            )

            if download_remote_images_enabled():
                markdown_text, saved_images = download_remote_images(
                    markdown_text, output_dir, base_url=html_base_url
                )
        else:
            saved_images = _extract_office_media(path, output_dir)

    if saved_images and not _markdown_has_image_refs(markdown_text):
        markdown_text = _append_image_refs(markdown_text, saved_images, output_dir)

    return IngestResult(
        markdown=markdown_text,
        images=saved_images,
        source_format=path.suffix.lstrip("."),
    )


def _extract_office_media(path: Path, output_dir: Path) -> list[Path]:
    if not zipfile.is_zipfile(path):
        return []

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.startswith(_OFFICE_MEDIA_PREFIXES):
                continue
            if name.endswith("/"):
                continue
            target = images_dir / Path(name).name
            target.write_bytes(z.read(name))
            saved.append(target)
            logger.debug("extracted_office_media path=%s", target)
    return saved


def _extract_epub_media(path: Path, output_dir: Path) -> list[Path]:
    """Extract every embedded image from an EPUB (a zip) into
    ``output_dir/images/``, keyed by basename.

    Unlike office formats, EPUB images sit at arbitrary in-zip paths, so we
    select by image extension rather than a fixed prefix. Basenames in real
    EPUBs are unique; on the rare collision the later member wins (logged at
    DEBUG), which is acceptable since markdown refs are matched by basename.
    """
    if not zipfile.is_zipfile(path):
        return []

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            if not name.lower().endswith(_IMAGE_EXTENSIONS):
                continue
            target = images_dir / Path(name).name
            target.write_bytes(z.read(name))
            saved.append(target)
            logger.debug("extracted_epub_media path=%s", target)
    return saved


def _retarget_image_refs(markdown: str, images: list[Path]) -> str:
    """Rewrite `![alt](<anything>/<name>)` to `![alt](images/<name>)` for
    every ref whose basename matches an extracted image.

    MarkItDown emits EPUB refs relative to the in-zip chapter location
    (`../images/..`), which is wrong once the markdown is flattened to a
    single file at the output root. Refs without a matching extracted image
    are left untouched.
    """
    names = {img.name for img in images}
    if not names:
        return markdown

    def repl(match: re.Match[str]) -> str:
        basename = match.group(2).rsplit("/", 1)[-1]
        if basename in names:
            return f"{match.group(1)}images/{basename}{match.group(3)}"
        return match.group(0)

    return _MD_IMAGE_REF_RE.sub(repl, markdown)


def _markdown_has_image_refs(markdown: str) -> bool:
    return "![" in markdown and "](" in markdown


def _append_image_refs(markdown: str, images: list[Path], output_dir: Path | None) -> str:
    if not images:
        return markdown
    lines = ["", "", "## Extracted Images", ""]
    for img in images:
        rel = img.name if output_dir is None else f"images/{img.name}"
        lines.append(f"![{img.name}]({rel})")
        lines.append("")
    return markdown + "\n".join(lines)
