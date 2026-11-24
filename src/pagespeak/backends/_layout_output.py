"""Layout backend: what a build writes besides its markdown — the picture crops, and the
source map `pagespeak verify` checks the document against."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..services._source_map import write_source_map
from ._layout_pages import render_page
from ._layout_profile import LayoutProfile

Crop = tuple[int, list[float], str, int]
CROP_SCALE = 2.0
JPEG_QUALITY = 88


def clip_crops(doc: Any, crops: list[Crop]) -> list[Crop]:
    """Each crop held to its page's edge: what is cut, and what the source map records."""
    out: list[Crop] = []
    for pg, (x0, y0, x1, y1), name, turn in crops:
        left, bottom, right, top = doc[pg].get_cropbox()
        out.append((pg, [max(x0, left), max(y0, bottom), min(x1, right), min(y1, top)], name, turn))
    return out


def render_crops(doc: Any, crops: list[Crop], img_dir: Path) -> list[Path]:
    """Render each crop's page at `CROP_SCALE` and save the crop (turned upright when it was printed sideways)."""
    img_dir.mkdir(parents=True, exist_ok=True)
    by_page: dict[int, list[tuple[list[float], str, int]]] = {}
    for pg, box, name, turn in clip_crops(doc, crops):
        by_page.setdefault(pg, []).append((box, name, turn))
    for pg, items in by_page.items():
        p = doc[pg]
        left, _, _, top = p.get_cropbox()
        img = render_page(p, CROP_SCALE).convert("RGB")
        for (x0, y0, x1, y1), name, turn in items:
            crop = img.crop(
                (
                    round((x0 - left) * CROP_SCALE),
                    round((top - y1) * CROP_SCALE),
                    round((x1 - left) * CROP_SCALE),
                    round((top - y0) * CROP_SCALE),
                )
            )
            (crop.rotate(turn, expand=True) if turn else crop).save(
                img_dir / name, quality=JPEG_QUALITY
            )
    return [img_dir / name for _, _, name, _ in crops]


def _ranges(pages: list[int]) -> list[tuple[int, int]]:
    """1-based page numbers → [(first, last)] runs."""
    out: list[tuple[int, int]] = []
    for p in sorted(set(pages)):
        if out and p == out[-1][1] + 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


def write_layout_source_map(
    out_dir: Path,
    pdf: Path,
    prof: LayoutProfile,
    read: list[int],
    crops: list[Crop],
    bottom: float = 0.0,
) -> Path:
    """The map of what the build read and where it cut each picture, with what it leaves out on purpose.

    `bottom` is the pages' bottom edge: the body band runs from there to the profile's `head_y`.
    """
    left_out = [
        (
            pg + 1,
            (spec["figure"][0], bottom, spec["figure"][2], spec["figure"][1]),
            f"{spec['title'].split('.')[0]} is printed as a picture with no text layer: transcribed into a markdown table",
        )
        for pg, spec in prof.raster_tables.items()
    ]
    return write_source_map(
        out_dir,
        pdf=pdf,
        pages=_ranges([pg + 1 for pg in read]),
        body=(bottom, float(prof.head_y)),
        pictures=[(name, pg + 1, (box[0], box[1], box[2], box[3])) for pg, box, name, _ in crops],
        left_out=left_out,
        left_out_text=list(prof.left_out_text),
    )
