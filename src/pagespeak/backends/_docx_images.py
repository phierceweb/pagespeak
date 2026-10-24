"""Inline Word images (DrawingML and VML) as positional `![alt](images/..)`
refs, with the image bytes written under `<output_dir>/images/`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx.oxml.ns import qn

from ..utils._alt import flatten_alt


def _add_image_ref(
    rid: str | None,
    paragraph: Any,
    rels: Any,
    images_dir: Path,
    refs: list[str],
) -> None:
    if not rid or rid not in rels:
        return
    part = rels[rid].target_part
    images_dir.mkdir(parents=True, exist_ok=True)
    target = images_dir / Path(part.partname).name
    stem, suffix = target.stem, target.suffix
    n = 2
    while target.exists() and target.read_bytes() != part.blob:
        target = images_dir / f"{stem}-{n}{suffix}"
        n += 1
    if not target.exists():
        target.write_bytes(part.blob)
    alt = ""
    for docpr in paragraph._p.iter(qn("wp:docPr")):
        alt = docpr.get("descr") or docpr.get("title") or ""
        if alt:
            break
    refs.append(f"![{flatten_alt(alt)}](images/{target.name})")


_VML_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"


def _emit_images(paragraph: Any, output_dir: Path | None) -> list[str]:
    """Positional ``![alt](images/..)`` refs for inline drawings/pict in
    this paragraph; image bytes written under output_dir/images/."""
    if output_dir is None:
        return []
    refs: list[str] = []
    rels = paragraph.part.rels
    images_dir = output_dir / "images"
    for blip in paragraph._p.iter(qn("a:blip")):
        _add_image_ref(blip.get(qn("r:embed")), paragraph, rels, images_dir, refs)
    for imgdata in paragraph._p.iter(_VML_IMAGEDATA):
        _add_image_ref(imgdata.get(qn("r:id")), paragraph, rels, images_dir, refs)
    return refs
