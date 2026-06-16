"""Top Hat quiz-export PDF → per-question markdown.

Top Hat's "Export" produces a print-to-PDF of its web quiz page. Marker and
Docling both *damage* it: Marker shreds every answer option into a
one-word-per-line table; Docling de-shreds but drops whole questions and
triple-duplicates the rest. The cause is the same — Top Hat's multi-column
"Show Correct Answer / Show Responses" answer-card layout breaks table
detection in both engines.

The PDF's underlying text layer, however, is pristine in reading order: every
`<Prefix> Question <N>` marker, every stem, every option survives. So this
backend ignores layout entirely — it reads the text layer via `pypdfium2`,
strips the web chrome, and promotes each `Question N` marker to a
`## Question N` heading. The quiz title is the only `#` H1, so the pipeline's
section splitter cuts one file per question (the Canvas QTI shape).

The work is split across focused modules:

- `_tophat_parse` — text lines → `TopHatQuiz` model (chrome strip, segmentation,
  stem/option parsing).
- `_tophat_answers` — the *visual* answer key: when an export is taken after the
  due date the correct option's letter glyph is light grey; detect it by fill
  color and mark it.
- `_tophat_images` — extract embedded figures (a diagram can BE the whole
  question) and bind them to their question for the vision pass.
- `_tophat_render` — `TopHatQuiz` → markdown.

This module holds the data model, the text-layer reader, and the
`convert_pdf_tophat` entry point. Selected via `--pdf-backend tophat`
(or `pdf_backend="tophat"`). See `docs/tophat-quizzes.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pf_core.log import get_logger

from ..models._models import IngestResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class TopHatQuestion:
    """One quiz question: number, stem, options, correct letter(s), and figures.

    `correct` is the set of correct option letters (from the visual answer key,
    see `_tophat_answers`). Empty for a questions-only export, a fill-in-the-blank
    question, or a discussion prompt. `blanks` holds a fill-in-the-blank
    question's answer value(s) (text, not letters). `images` is the relative
    paths of any extracted figures bound to this question (see `_tophat_images`)
    — a figure question (a diagram with no text stem) carries an image and no
    options.
    """

    number: int
    stem: str
    options: list[tuple[str, str]]
    correct: tuple[str, ...] = ()
    images: tuple[str, ...] = ()
    blanks: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopHatQuiz:
    """A parsed Top Hat quiz: title, optional subtitle/export line, questions."""

    title: str
    subtitle: str | None
    exported: str | None
    questions: list[TopHatQuestion]


def extract_lines(path: Path) -> list[str]:
    """Extract the PDF text layer as a flat list of lines (reading order).

    Uses `pypdfium2` (ships with the `pdf` / `pdf-docling` extras; also the
    light `tophat` extra). No layout/table inference — that is exactly what we
    want to avoid for Top Hat exports.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as e:  # pragma: no cover - import guard
        raise ImportError(
            "The Top Hat PDF backend requires pypdfium2. "
            "Install with: pip install pagespeak[tophat]"
        ) from e

    pdf = pdfium.PdfDocument(str(path))
    lines: list[str] = []
    for i in range(len(pdf)):
        text = pdf[i].get_textpage().get_text_bounded()
        lines.extend(text.splitlines())
    return [ln.strip() for ln in lines]


def convert_pdf_tophat(
    path: Path,
    *,
    output_dir: Path | None = None,
    force_ocr: bool = False,
    device: str | None = None,
    page_range: str | list[int] | None = None,
    backend_kwargs: dict[str, object] | None = None,
) -> IngestResult:
    """Convert a Top Hat quiz-export PDF to per-question markdown.

    Matches the `PdfConverter` signature so it slots into `_pdf_dispatch`.
    `force_ocr`, `device`, `page_range`, and `backend_kwargs` are accepted for
    protocol compatibility and ignored. When `output_dir` is given, embedded
    figures are extracted into `output_dir/images/` and referenced in the
    relevant question (so the vision pass can caption them); without it, the
    conversion is text-only.

    Raises:
        ValueError: if the PDF has no Top Hat question markers (a backend
            mismatch — use `--pdf-backend marker`/`docling` for a normal PDF).
    """
    from ._tophat_answers import extract_correct_answers
    from ._tophat_parse import looks_like_tophat, parse_quiz
    from ._tophat_render import render_quiz

    lines = extract_lines(path)
    if not looks_like_tophat(lines):
        raise ValueError(
            f"{path.name!r} doesn't look like a Top Hat quiz export "
            "(no 'Question N … Correct Answer' markers). "
            "Use --pdf-backend marker or docling for an ordinary PDF."
        )

    answers = extract_correct_answers(path)
    images_map: dict[int, list[str]] = {}
    if output_dir is not None:
        from ._tophat_images import extract_question_images

        images_map = extract_question_images(path, output_dir / "images")
    quiz = parse_quiz(lines, answers, images_map)
    image_paths = (
        [output_dir / rel for rels in images_map.values() for rel in rels]
        if output_dir is not None
        else []
    )
    logger.debug(
        "tophat_convert title=%r questions=%d answered=%d figures=%d",
        quiz.title,
        len(quiz.questions),
        sum(1 for q in quiz.questions if q.correct),
        len(image_paths),
    )
    return IngestResult(
        markdown=render_quiz(quiz),
        images=image_paths,
        diagrams=[],
        source_format="pdf",
    )
