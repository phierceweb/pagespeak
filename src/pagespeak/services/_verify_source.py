"""Verify checks that read the source PDF.

Finds the PDF a document was converted from — the source map's while its
SHA-256 still matches, else the file of that name and SHA-256 under the input
folder (the run record's `source_identity` when there is no map) — reads its
text layer once, and runs the checks that
compare against it: printed titles and the outline always; line coverage,
line joins and picture coverage when the build wrote a source map. A check
that cannot run says why.
"""

from __future__ import annotations

import glob
from pathlib import Path

from pw_core.pipeline.run_record import file_sha256

from ._pdf_lines import PdfPage, page_count, read_outline, read_pages
from ._source_map import SourceMap
from ._staging import find_source_pdf
from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult
from ._verify_lines import body_lines, check_line_coverage, check_line_joins
from ._verify_pictures import check_picture_coverage
from ._verify_structure import check_outline
from ._verify_titles import check_printed_titles

MAP_CHECKS = ("line_coverage", "line_joins", "picture_coverage")
SOURCE_CHECKS = ("printed_titles", "outline", *MAP_CHECKS)
_NO_MAP = "no source map: only a build that records what it read and where it cut each picture can be checked line by line"


def _identity(doc: VerifyDoc) -> tuple[str | None, str | None]:
    record = doc.run_record or {}
    identity = record.get("source_identity")
    if isinstance(identity, dict) and isinstance(identity.get("file"), str):
        sha = identity.get("sha256")
        return identity["file"], sha if isinstance(sha, str) else None
    name = record.get("input")
    return (name if isinstance(name, str) else None), None


def _sha256(path: Path) -> str | None:
    """The file's SHA-256, or None when it cannot be read."""
    try:
        return file_sha256(path)
    except OSError:
        return None


def locate_pdf(doc: VerifyDoc, smap: SourceMap | None, in_dir: Path) -> tuple[Path | None, str]:
    """The source PDF, or None and the reason it was not found."""
    if smap is not None:
        digest = _sha256(smap.pdf) if smap.pdf.is_file() and smap.sha256 is not None else None
        if smap.pdf.is_file() and (smap.sha256 is None or digest == smap.sha256):
            return smap.pdf, ""
        if not smap.pdf.is_file():
            state = "is gone"
        else:
            state = "cannot be read" if digest is None else "has changed since the build"
        found, reason = _lookup(doc, smap.pdf.name, smap.sha256, in_dir)
        if found is None:
            return None, f"the PDF the source map names {state} ({smap.pdf}); {reason}"
        return found, ""
    name, sha = _identity(doc)
    if name is not None and not name.lower().endswith(".pdf") and not name.endswith(".md"):
        return None, f"the source is {Path(name).suffix or name}, not a PDF"
    return _lookup(doc, name, sha, in_dir)


def _lookup(
    doc: VerifyDoc, name: str | None, sha: str | None, in_dir: Path
) -> tuple[Path | None, str]:
    found: Path | None = None
    if name is not None and name.lower().endswith(".pdf") and in_dir.is_dir():
        pattern = glob.escape(Path(name).name)
        found = next((p for p in sorted(in_dir.rglob(pattern)) if p.is_file()), None)
    if found is None:
        found = find_source_pdf(doc.name, in_dir)
    if found is None:
        return None, f"no source PDF found under {in_dir}"
    if sha is not None and (digest := _sha256(found)) != sha:
        if digest is None:
            return None, f"could not read {found.name} under {in_dir}"
        return (
            None,
            f"{found.name} under {in_dir} is not the file that was converted (SHA-256 differs)",
        )
    return found, ""


def source_checks(
    doc: VerifyDoc, smap: SourceMap | None, located: tuple[Path | None, str]
) -> list[CheckResult]:
    """The checks against the PDF `locate_pdf` found (or why it found none)."""
    pdf, reason = located
    if pdf is None:
        return [CheckResult(check, skipped=reason) for check in SOURCE_CHECKS]
    try:
        numbers = smap.page_numbers() if smap is not None else range(1, page_count(pdf) + 1)
        pages = read_pages(pdf, numbers, glyphs=smap.glyph_tables() if smap is not None else None)
        outline = read_outline(pdf)
    except ImportError:
        reason = "needs pypdfium2 (the pdf, pdf-docling or tophat extra)"
        return [CheckResult(check, skipped=reason) for check in SOURCE_CHECKS]
    except RuntimeError as exc:  # pdfium's PdfiumError: a damaged or locked file
        reason = f"could not read {pdf.name}: {exc}"
        return [CheckResult(check, skipped=reason) for check in SOURCE_CHECKS]
    # Without a map nothing says which lines are running heads or sit inside a
    # cropped picture, so every line counts and a bare missing label is a note.
    body = pages
    if smap is not None:
        body = {n: PdfPage(n, p.box, body_lines(p, smap)) for n, p in pages.items()}
    claimed = set(smap.page_numbers()) if smap is not None else None
    results = [
        check_printed_titles(doc, body, keep=lambda _line: True, strict=smap is not None),
        check_outline(doc, outline, claimed_pages=claimed),
    ]
    if smap is None:
        return results + [CheckResult(c, skipped=_NO_MAP) for c in MAP_CHECKS]
    return results + [
        check_line_coverage(doc, pages, smap),
        check_line_joins(doc, pages, smap),
        check_picture_coverage(doc, pages, smap, pdf=pdf),
    ]
