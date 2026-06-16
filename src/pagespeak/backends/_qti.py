"""Canvas QTI quiz-export backend (fan-out model).

Each quiz in a Canvas Classic Quizzes export (IMS Common Cartridge + QTI
1.2) becomes its **own independent full-pipeline document** — the export
fans out into N per-exam pipeline runs, orchestrated by
`orchestrators/_qti_export`. This module provides the QTI-specific pieces
that fan-out uses:

- `enumerate_quizzes(src)` — discovery: resolve the export (dir or
  `.imscc`/`.zip`), read the manifest + course + each exam's XML, and map
  the media files.
- `convert_qti_exam(exam, export, out_dir)` — per-exam ingest: render one
  exam's markdown (`# title` + `## Question N` blocks) and copy only the
  figures it references into `<out_dir>/images/`.
- `split_quiz_into_questions(exam_md, sections_dir, …)` — split one exam's
  markdown into one self-contained `Question NNN.md` per question, each with
  rich provenance frontmatter.

Everything is manifest-driven; nothing about the number of quizzes or the
media set is hardcoded.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from pf_core.log import get_logger

from ..models._models import IngestResult
from ._qti_parse import parse_assessment_meta, parse_quiz
from ._qti_render import render_quiz

logger = get_logger(__name__)

_QTI_RESOURCE_TYPE = "imsqti_xmlv1p2"
_WEBCONTENT_TYPE = "webcontent"
_MANIFEST_NAME = "imsmanifest.xml"
QTI_SUFFIXES: frozenset[str] = frozenset({".imscc", ".zip"})

_COURSE_RE = re.compile(r'for course\s+"([^"]+)"', re.IGNORECASE)


# --------------------------------------------------------------------------
# Detection + low-level parsing
# --------------------------------------------------------------------------


def is_qti_export(path: str | Path) -> bool:
    """True if `path` is a Canvas QTI export — a directory containing
    `imsmanifest.xml`, or an `.imscc`/`.zip` archive containing one."""
    p = Path(path)
    if p.is_dir():
        return (p / _MANIFEST_NAME).exists()
    if p.suffix.lower() in QTI_SUFFIXES:
        try:
            with zipfile.ZipFile(p) as zf:
                return any(n.rsplit("/", 1)[-1] == _MANIFEST_NAME for n in zf.namelist())
        except (zipfile.BadZipFile, OSError):
            return False
    return False


def _resolve_root(src: Path) -> tuple[Path, bool]:
    """Return `(export_root, is_temp)`. Unzips an archive to a temp dir."""
    if src.is_dir():
        return src, False
    tmp = Path(tempfile.mkdtemp(prefix="pagespeak_qti_"))
    with zipfile.ZipFile(src) as zf:
        zf.extractall(tmp)
    if (tmp / _MANIFEST_NAME).exists():
        return tmp, True
    for cand in tmp.rglob(_MANIFEST_NAME):
        return cand.parent, True
    return tmp, True


def _extract_course(manifest_xml: str) -> str:
    """Course name from the manifest's LOM title (`…for course "<name>"`),
    or the raw title string, or `""`. The durable per-export linkage key."""
    try:
        root = ET.fromstring(manifest_xml)
    except ET.ParseError:
        return ""
    strings = root.findall(".//{*}title//{*}string")
    for s in strings:
        m = _COURSE_RE.search(s.text or "")
        if m:
            return m.group(1).strip()
    return (strings[0].text or "").strip() if strings else ""


def _parse_manifest(xml_text: str) -> tuple[list[tuple[str, str, str | None]], list[str]]:
    """Parse `imsmanifest.xml` → `(quizzes, media_hrefs)` where `quizzes` is
    `(quiz_id, qti_xml_href, meta_xml_href)` and `media_hrefs` are webcontent
    file hrefs (relative to the export root)."""
    root = ET.fromstring(xml_text)
    href_by_id: dict[str, str | None] = {}
    quiz_resources: list[tuple[str, str | None, str | None]] = []
    media_hrefs: list[str] = []

    for res in root.findall(".//{*}resource"):
        rtype = res.get("type", "")
        ident = res.get("identifier", "")
        file_el = res.find("{*}file")
        href = file_el.get("href") if file_el is not None else res.get("href")
        href_by_id[ident] = href
        if rtype == _QTI_RESOURCE_TYPE:
            dep = res.find("{*}dependency")
            dep_ref = dep.get("identifierref") if dep is not None else None
            quiz_resources.append((ident, href, dep_ref))
        elif rtype == _WEBCONTENT_TYPE and href:
            media_hrefs.append(href)

    quizzes: list[tuple[str, str, str | None]] = []
    for quiz_id, qti_href, dep_ref in quiz_resources:
        if not qti_href:
            continue
        meta_href = href_by_id.get(dep_ref) if dep_ref else None
        if not meta_href:
            meta_href = str(Path(qti_href).parent / "assessment_meta.xml")
        quizzes.append((quiz_id, qti_href, meta_href))
    return quizzes, media_hrefs


def _safe_image_name(name: str) -> str:
    """Filesystem- and markdown-link-safe image filename.

    Canvas media names contain spaces and parentheses (e.g.
    ``Screen Shot 2020 (1).png``), which corrupt a `![](images/…)` link —
    the `)` inside the name terminates the link early. Collapse anything
    outside ``[A-Za-z0-9._-]`` to ``_`` so paths are safe everywhere.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return re.sub(r"_{2,}", "_", safe).strip("_") or "image"


def _sanitize_quiz_title(title: str) -> str:
    """Filesystem-safe base name (no extension) for a quiz/exam title."""
    name = title.replace("/", " - ").replace("\\", " - ").replace(":", " -")
    for ch in ("*", "?", '"'):
        name = name.replace(ch, "")
    name = name.replace("<", "(").replace(">", ")")
    return re.sub(r"\s{2,}", " ", name).strip()[:200].rstrip() or "quiz"


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


@dataclass
class QtiExam:
    """One quiz's parsed XML + identity (the per-exam ingest input)."""

    title: str
    quiz_id: str
    qti_xml: str
    meta_xml: str
    points_possible: float


@dataclass
class QtiExport:
    """A resolved Canvas QTI export: the exams + shared media + course.

    `root` is the on-disk export root (a temp dir when `is_temp`, which the
    caller must `shutil.rmtree` after all exams are converted, since the
    media files live there until each exam copies the ones it references).
    """

    course: str
    exams: list[QtiExam]
    media: dict[str, Path]  # decoded basename -> source file path
    root: Path
    is_temp: bool


def _safe_join(root: Path, href: str) -> Path:
    """Resolve a manifest-relative ``href`` under ``root``, rejecting traversal.

    A Canvas export's resource/media hrefs are always inside the export tree.
    A ``..`` or absolute href that resolves outside ``root`` indicates a
    malicious archive — ``root / href`` would otherwise read (and surface into
    the output markdown + vision payload) an arbitrary file. Raises ValueError.
    """
    root_resolved = root.resolve()
    candidate = (root / unquote(href)).resolve()
    if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
        raise ValueError(f"manifest href escapes the export root: {href!r}")
    return candidate


def enumerate_quizzes(src: str | Path) -> QtiExport:
    """Resolve an export and read its exams + media map (no rendering yet)."""
    src_path = Path(src)
    root, is_temp = _resolve_root(src_path)
    manifest_xml = (root / _MANIFEST_NAME).read_text(encoding="utf-8")
    course = _extract_course(manifest_xml)
    quiz_files, media_hrefs = _parse_manifest(manifest_xml)

    media: dict[str, Path] = {}
    for href in media_hrefs:
        p = _safe_join(root, href)
        media[p.name] = p

    exams: list[QtiExam] = []
    for quiz_id, qti_href, meta_href in quiz_files:
        qti_xml = _safe_join(root, qti_href).read_text(encoding="utf-8")
        meta_path = _safe_join(root, meta_href) if meta_href else None
        meta_xml = (
            meta_path.read_text(encoding="utf-8") if meta_path and meta_path.is_file() else ""
        )
        title, points, _ = parse_assessment_meta(meta_xml) if meta_xml else ("", 0.0, "")
        exams.append(
            QtiExam(
                title=title or f"Quiz {quiz_id}",
                quiz_id=quiz_id,
                qti_xml=qti_xml,
                meta_xml=meta_xml,
                points_possible=points,
            )
        )
    return QtiExport(
        course=course,
        exams=exams,
        media=media,
        root=root,
        is_temp=is_temp,
    )


# --------------------------------------------------------------------------
# Per-exam ingest
# --------------------------------------------------------------------------


def _make_copying_resolver(
    media: dict[str, Path], images_dir: Path, copied: dict[str, Path]
) -> Callable[[str], str]:
    """Resolver that copies (once, link-safe-named) only the figures an exam
    actually references, into `images_dir`. Records copies in `copied`."""

    def resolve(src: str) -> str:
        if not src:
            return ""
        raw = unquote(src).rsplit("/", 1)[-1]
        src_file = media.get(raw)
        if src_file is None or not src_file.is_file():
            return ""
        safe = _safe_image_name(raw)
        if safe not in copied:
            images_dir.mkdir(parents=True, exist_ok=True)
            target = images_dir / safe
            shutil.copy2(src_file, target)
            copied[safe] = target
        return f"images/{safe}"

    return resolve


def convert_qti_exam(
    exam: QtiExam, export: QtiExport, output_dir: str | Path, *, answer_key: bool = True
) -> IngestResult:
    """Ingest ONE exam: render its markdown (`# title` + `## Question N`
    blocks) and copy only the figures it references into
    `<output_dir>/images/`. Writes `<sanitized title>.raw.md` and returns
    the `IngestResult` (the raw checkpoint for the per-exam pipeline)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Path] = {}
    resolver = _make_copying_resolver(export.media, out / "images", copied)

    quiz = parse_quiz(exam.qti_xml, exam.meta_xml, media_resolver=resolver)
    markdown = render_quiz(quiz, answer_key=answer_key)
    stem = _sanitize_quiz_title(exam.title)
    (out / f"{stem}.raw.md").write_text(markdown, encoding="utf-8")
    logger.debug(
        "qti_exam_ingest exam=%s questions=%d images=%d", stem, len(quiz.questions), len(copied)
    )
    return IngestResult(markdown=markdown, images=list(copied.values()), source_format="qti")


__all__ = [
    "QtiExam",
    "QtiExport",
    "QTI_SUFFIXES",
    "convert_qti_exam",
    "enumerate_quizzes",
    "is_qti_export",
]
