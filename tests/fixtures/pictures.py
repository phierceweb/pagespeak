"""Small PNG pictures whose perceptual hashes differ, for verify's picture checks."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def picture(path: Path, shape: int) -> Path:
    """A picture whose perceptual hash differs with `shape`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("L", (64, 64), 255)
    draw = ImageDraw.Draw(img)
    if shape == 0:
        draw.rectangle((4, 4, 30, 60), fill=0)
    elif shape == 1:
        draw.ellipse((10, 10, 60, 40), fill=0)
    else:
        draw.polygon([(0, 63), (63, 63), (32, 0)], fill=0)
    img.save(path)
    return path
