"""`pagespeak pictures`: settle a document's pictures before captions are paid for.

Lists every file in `images/` that vision may send, with the label the text
gives it before vision, whether a caption is already cached, and which labels
say nothing about their picture; runs verify's source checks that concern
pictures. Read-only, $0.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pw_foundation.exceptions import InvalidInputError

from ..utils._phash import compute_phash
from ._image_files import image_files
from ._source_map import read_source_map
from ._verify_captions import describes_picture, pre_vision_checkpoint
from ._verify_doc import VerifyDoc, default_in_dir
from ._verify_finding import CheckResult
from ._verify_source import locate_pdf, source_checks
from ._vision_inject import alt_text_by_basename

PICTURE_CHECKS = ("picture_coverage", "printed_titles")


@dataclass(frozen=True)
class Picture:
    """One file in `images/` and what the text and the vision cache hold for it."""

    path: Path
    referenced: bool
    label: str
    size: tuple[int, int] | None
    captioned: bool

    @property
    def unlabelled(self) -> bool:
        return self.referenced and not self.label.strip()

    @property
    def label_says_nothing(self) -> bool:
        return self.referenced and bool(self.label.strip()) and not describes_picture(self.label)


@dataclass(frozen=True)
class PictureReport:
    doc: VerifyDoc
    labels_from: Path
    pictures: tuple[Picture, ...]
    checks: tuple[CheckResult, ...]

    @property
    def referenced(self) -> list[Picture]:
        return [p for p in self.pictures if p.referenced]


def _size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as im:
            width, height = im.size
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    return (width, height)


def _captioned(path: Path, cache: Path) -> bool:
    try:
        phash = compute_phash(path)
    except (OSError, ValueError, Image.DecompressionBombError):  # a vector or damaged picture
        return False
    return (cache / f"{phash}.json").is_file()


def _picture_checks(doc: VerifyDoc, in_dir: Path | None) -> tuple[CheckResult, ...]:
    try:
        smap = read_source_map(doc.root)
    except InvalidInputError as exc:
        return tuple(
            CheckResult(c, skipped=f"source map unreadable: {exc}") for c in PICTURE_CHECKS
        )
    located = locate_pdf(doc, smap, in_dir or default_in_dir(doc.root))
    return tuple(r for r in source_checks(doc, smap, located) if r.check in PICTURE_CHECKS)


def picture_report(doc: VerifyDoc, *, in_dir: Path | None = None) -> PictureReport:
    """Every picture of `doc`, labelled from the last checkpoint before vision."""
    labels_from = pre_vision_checkpoint(doc) or doc.master
    labels = alt_text_by_basename(labels_from.read_text(encoding="utf-8", errors="replace"))
    cache = doc.root / ".vision-cache"
    files = image_files(doc.images_dir)
    pictures = tuple(
        Picture(
            path=p,
            referenced=p.name in labels,
            label=labels.get(p.name, ""),
            size=_size(p),
            captioned=p.name in labels and _captioned(p, cache),
        )
        for p in files
    )
    return PictureReport(doc, labels_from, pictures, _picture_checks(doc, in_dir))


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def render_report(report: PictureReport, sheet: Path, *, list_limit: int = 40) -> str:
    """The terminal summary: counts, the labels that say nothing, the checks."""
    shown = report.referenced
    silent = [p for p in shown if p.label_says_nothing]
    uncached = sum(1 for p in shown if not p.captioned)
    out = [
        f"{report.doc.name}: {_count(len(shown), 'picture')} in the text, "
        f"{len(report.pictures) - len(shown)} more in images/ not in the text "
        f"(labels from {report.labels_from.name})",
        f"  captions cached: {len(shown) - uncached}; without one: {uncached}",
        f"  with no label: {sum(1 for p in shown if p.unlabelled)}",
        f"  labels that say nothing about their picture: {len(silent)}",
    ]
    for p in silent[:list_limit]:
        cached = "  (caption cached)" if p.captioned else ""
        rel = p.path.relative_to(report.doc.images_dir).as_posix()
        out.append(f"    images/{rel}  {p.label.strip()[:60]!r}{cached}")
    if len(silent) > list_limit:
        out.append(f"    … and {len(silent) - list_limit} more on the contact sheet")
    for result in report.checks:
        if not result.ran:
            out.append(f"  {result.check}: did not run ({result.skipped})")
            continue
        out.append(f"  {result.check}: {len(result.findings)} finding(s)")
        out += [f"    {f.where}: {f.message}" for f in result.findings[:list_limit]]
    out.append(f"  contact sheet: {sheet}")
    return "\n".join(out)


__all__ = ["PICTURE_CHECKS", "Picture", "PictureReport", "picture_report", "render_report"]
