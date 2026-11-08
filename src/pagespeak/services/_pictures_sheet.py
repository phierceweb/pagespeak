"""The contact sheet `pagespeak pictures` writes: every picture of a document on one page."""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

from pw_foundation.utils.io import atomic_write_text

from ._pictures import Picture, PictureReport

SHEET_FILENAME = ".pagespeak-pictures.html"

_STYLE = """
:root { color-scheme: light dark; --line: #8884; --warn: #c2410c; --ok: #15803d; }
body { font: 14px/1.4 system-ui, sans-serif; margin: 16px; }
h1 { font-size: 20px; } h2 { font-size: 16px; margin-top: 28px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
figure { margin: 0; border: 1px solid var(--line); border-radius: 6px; padding: 8px; }
img { display: block; max-width: 100%; max-height: 220px; margin: 0 auto 6px; }
figcaption { font-size: 12px; overflow-wrap: anywhere; }
.name { font-family: ui-monospace, monospace; }
.tag { display: inline-block; font-size: 11px; padding: 0 4px; border-radius: 3px; border: 1px solid; }
.silent { color: var(--warn); } .cached { color: var(--ok); }
"""


def _card(picture: Picture, images_dir: Path) -> str:
    name = picture.path.relative_to(images_dir).as_posix()
    size = f"{picture.size[0]}×{picture.size[1]}" if picture.size else "size unknown"
    tags = []
    if picture.label_says_nothing:
        tags.append('<span class="tag silent">label says nothing</span>')
    if picture.unlabelled:
        tags.append('<span class="tag silent">no label</span>')
    if picture.captioned:
        tags.append('<span class="tag cached">caption cached</span>')
    label = escape(picture.label.strip()) if picture.label.strip() else "<em>no label</em>"
    return (
        f'<figure><img loading="lazy" src="images/{quote(name)}" alt="{escape(name)}">'
        f'<figcaption><span class="name">{escape(name)}</span> · {size}<br>{label}<br>'
        f"{' '.join(tags)}</figcaption></figure>"
    )


def _section(title: str, pictures: list[Picture], images_dir: Path) -> str:
    if not pictures:
        return ""
    cards = "\n".join(_card(p, images_dir) for p in pictures)
    return f'<h2>{escape(title)} ({len(pictures)})</h2>\n<div class="grid">\n{cards}\n</div>'


def render_sheet(report: PictureReport) -> str:
    shown = report.referenced
    silent = [p for p in shown if p.label_says_nothing or p.unlabelled]
    labelled = [p for p in shown if p not in silent]
    unused = [p for p in report.pictures if not p.referenced]
    body = "\n".join(
        s
        for s in (
            _section(
                "In the text, with no label or one that says nothing", silent, report.doc.images_dir
            ),
            _section("In the text", labelled, report.doc.images_dir),
            _section("In images/ but not in the text", unused, report.doc.images_dir),
        )
        if s
    )
    title = escape(f"Pictures: {report.doc.name}")
    return (
        f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_STYLE}</style></head>\n<body>\n<h1>{title}</h1>\n"
        f"<p>Labels read from {escape(report.labels_from.name)}.</p>\n{body}\n</body></html>\n"
    )


def write_sheet(report: PictureReport) -> Path:
    """Write the contact sheet beside the document's master; returns its path."""
    path = report.doc.root / SHEET_FILENAME
    atomic_write_text(path, render_sheet(report))
    return path


__all__ = ["SHEET_FILENAME", "render_sheet", "write_sheet"]
