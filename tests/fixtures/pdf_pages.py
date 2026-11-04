"""Small PDFs for the verify tests, built with fpdf2.

Text lines, ink drawings, grey boxes, rules and bookmarks at known places.
Positions are PDF points from the page's top-left (fpdf's convention); pdfium
reports them from the bottom-left, so something placed at `top` reads back
near `PAGE_HEIGHT - top`. A text line's `top` is its baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PAGE_WIDTH, PAGE_HEIGHT = 612.0, 792.0


@dataclass
class Page:
    lines: list[tuple[float, float, float, str]] = field(default_factory=list)  # x, top, size, text
    drawings: list[tuple[float, float, float, float]] = field(default_factory=list)  # x, top, w, h
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)  # grey fill
    rules: list[tuple[float, float, float, float]] = field(
        default_factory=list
    )  # x1, top1, x2, top2
    panels: list[tuple[float, float, float, float]] = field(default_factory=list)  # rounded outline
    panel_radius: float = 8.0
    frames: list[tuple[float, float, float, float]] = field(
        default_factory=list
    )  # a hairline frame drawn as a filled ring, open at the top for a title
    polygons: list[list[tuple[float, float]]] = field(default_factory=list)  # solid black fill
    bookmark: tuple[int, str] | None = None  # outline level (0 = top), title


def body_lines(
    texts: list[str], *, x: float = 72, top: float = 100, step: float = 14
) -> list[tuple[float, float, float, str]]:
    """`texts` as consecutive 10pt body lines down one column."""
    return [(x, top + i * step, 10, t) for i, t in enumerate(texts)]


def make_pdf(path: Path, pages: list[Page]) -> Path:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.set_auto_page_break(False)
    pdf.set_font("Helvetica", size=10)
    for page in pages:
        pdf.add_page()
        if page.bookmark is not None:
            pdf.start_section(page.bookmark[1], level=page.bookmark[0])
        for x, top, size, text in page.lines:
            pdf.set_font("Helvetica", size=size)
            pdf.text(x, top, text)
        pdf.set_fill_color(200)
        for x, top, w, h in page.boxes:
            pdf.rect(x, top, w, h, style="F")
        pdf.set_fill_color(0)
        for x, top, w, h in page.drawings:
            pdf.ellipse(x, top, w, h, style="F")
        pdf.set_line_width(0.5)
        for x1, top1, x2, top2 in page.rules:
            pdf.line(x1, top1, x2, top2)
        pdf.set_line_width(1.5)
        for x, top, w, h in page.panels:
            pdf.rect(x, top, w, h, style="D", round_corners=True, corner_radius=page.panel_radius)
        for x, top, w, h in page.frames:
            pdf.polygon(_ring(x, top, w, h), style="F")
        for points in page.polygons:
            pdf.polygon(points, style="F")
    pdf.output(str(path))
    return path


def raw_pdf(
    path: Path,
    content: bytes,
    *,
    media: str = "0 0 612 792",
    crop: str | None = None,
    rotate: int = 0,
    annots: tuple[bytes, ...] = (),
    forms: dict[str, bytes] | None = None,
    images: dict[str, tuple[int, int, bytes]] | None = None,
) -> Path:
    """A one-page PDF written by hand, for what fpdf cannot set: a page's
    `/Rotate` or `/CropBox`, annotations, form XObjects (each a stream body
    drawn in the form's own space), and RGB images (name → width, height,
    pixel bytes) the page or a form draws by name. Positions are PDF points
    from the bottom-left; `/F1` is Helvetica."""
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    extra = [*annots]
    xobjects = []
    for name, body in (forms or {}).items():
        extra.append(_stream(b"/Type /XObject /Subtype /Form /BBox [-600 -600 1200 1200]", body))
        xobjects.append(b"/%s %d 0 R" % (name.encode(), 5 + len(extra)))
    image = b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8"
    for name, (width, height, pixels) in (images or {}).items():
        extra.append(_stream(image % (width, height), pixels))
        xobjects.append(b"/%s %d 0 R" % (name.encode(), 5 + len(extra)))
    annot_refs = b" ".join(b"%d 0 R" % (6 + i) for i in range(len(annots)))
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [%s] " % media.encode()
    page += b"/CropBox [%s] " % crop.encode() if crop else b""
    page += b"/Rotate %d " % rotate if rotate else b""
    page += b"/Resources << /Font << /F1 5 0 R >> /XObject << %s >> >> " % b" ".join(xobjects)
    page += b"/Contents 4 0 R /Annots [%s] >>" % annot_refs
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"]
    objs += [page, _stream(b"", content), font, *extra]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def _stream(head: bytes, body: bytes) -> bytes:
    return b"<< %s /Length %d >>\nstream\n%s\nendstream" % (head, len(body), body)


def text_at(x: float, y: float, text: str, size: float = 12) -> bytes:
    """A one-line text object at (x, y) for `raw_pdf`."""
    return b"BT /F1 %g Tf %g %g Td (%s) Tj ET\n" % (size, x, y, text.encode("latin-1"))


def disc(cx: float, cy: float, r: float) -> bytes:
    """A filled circle of bezier curves for `raw_pdf`: a drawing, never layout."""
    k = 0.5523 * r
    pts = (cx + r, cy, cx + r, cy + k, cx + k, cy + r, cx, cy + r, cx - k, cy + r, cx - r, cy + k)
    pts += (cx - r, cy, cx - r, cy - k, cx - k, cy - r, cx, cy - r, cx + k, cy - r, cx + r, cy - k)
    return (b"%g %g m " + b"%g %g %g %g %g %g c " * 4 + b"f\n") % (*pts, cx + r, cy)


def _ring(x: float, top: float, w: float, h: float, t: float = 0.5) -> list[tuple[float, float]]:
    """A frame `t` thick as one filled outline: in along the inside, back along the outside."""
    gap0, gap1, right, bottom = x + w / 3, x + 2 * w / 3, x + w, top + h
    return [
        (gap1, top), (gap1, top + t), (right - t, top + t), (right - t, bottom - t),
        (x + t, bottom - t), (x + t, top + t), (gap0, top + t), (gap0, top),
        (x, top), (x, bottom), (right, bottom), (right, top),
    ]  # fmt: skip
