"""Fan-out orchestrator for Canvas QTI exports.

A QTI export contains N quizzes; each becomes its **own independent
full-pipeline document**. `run_qti_export` enumerates the quizzes and, per
exam:

1. ingests it — `convert_qti_exam` renders one exam's markdown + copies only
   the figures it references → `<exam_dir>/<stem>.raw.md` + `images/`;
2. runs the standard Phase-3 pipeline over the exam dir (dir-mode
   `to_markdown`): cleanup → vision, writing per-exam stage checkpoints, a
   run record, and a per-exam `.vision-cache/`;
3. writes the whole-exam master doc with provenance frontmatter;
4. splits it into per-question documents under the exam's `sections/`.

`to_markdown` delegates here when it detects a QTI export, so the heavy
pipeline machinery (checkpoints, vision, run record) is reused unchanged —
this module only adds the QTI-specific ingest, the master-doc frontmatter,
and the per-question split.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pf_core.log import get_logger

from ..backends._qti import _sanitize_quiz_title, convert_qti_exam, enumerate_quizzes
from ..backends._qti_split import exam_frontmatter, split_quiz_into_questions
from ..models._models import Diagram, IngestResult
from ..services._cleanup import CleanupLevel

logger = get_logger(__name__)


def run_qti_export(
    src: str | Path,
    out: Path,
    *,
    diagrams: bool,
    cleanup: CleanupLevel,
    vision_backend: str | None,
    vision_model: str | None,
    vision_concurrency: int | None,
    vision_cache_only: bool,
    source_type: str | None,
    source_label: str | None,
    answer_key: bool,
    write_index: bool = True,
) -> IngestResult:
    """Convert a QTI export, one independent full-pipeline document per exam.

    Returns an aggregate `IngestResult` (all copied images + diagrams across
    exams; `source_format="qti"`). Per-exam outputs live under `out/<Exam>/`.
    """
    from .. import to_markdown  # lazy: avoids the _dispatch <-> _qti_export cycle

    # A Canvas QTI export is an exam; default its provenance source_type so it
    # is distinguishable from Top Hat quizzes (source_type="quiz") in QMD.
    # Explicit --source-type wins.
    source_type = source_type or "exam"

    out = Path(out)
    export = enumerate_quizzes(src)
    all_images: list[Path] = []
    all_diagrams: list[Diagram] = []
    try:
        for exam in export.exams:
            stem = _sanitize_quiz_title(exam.title)
            exam_dir = out / stem

            # 1. ingest this one exam → <stem>.raw.md + its own images/
            convert_qti_exam(exam, export, exam_dir, answer_key=answer_key)

            # 2. standard Phase-3 over the exam dir (dir-mode): cleanup →
            #    vision; per-exam checkpoints + run record + .vision-cache/.
            #    No generic split (the per-question split is QTI-specific).
            result = to_markdown(
                exam_dir,
                output_dir=exam_dir,
                diagrams=diagrams,
                cleanup=cleanup,
                vision_backend=vision_backend,  # type: ignore[arg-type]
                vision_model=vision_model,
                vision_concurrency=vision_concurrency,
                vision_cache_only=vision_cache_only,
                split_sections=False,
                regenerate_toc=False,
            )

            # 3. whole-exam master doc, with provenance frontmatter
            qcount = sum(1 for ln in result.markdown.splitlines() if ln.startswith("## Question "))
            front = exam_frontmatter(
                course=export.course,
                exam_title=exam.title,
                quiz_id=exam.quiz_id,
                points_possible=exam.points_possible,
                question_count=qcount,
                source_type=source_type,
                source_label=source_label,
            )
            (exam_dir / f"{stem}.md").write_text(
                front + result.markdown.lstrip("\n"), encoding="utf-8"
            )

            # 4. per-question split under the exam's own sections/
            split_quiz_into_questions(
                result.markdown,
                exam_dir / "sections",
                course=export.course,
                exam_title=exam.title,
                quiz_id=exam.quiz_id,
                source_type=source_type,
                source_label=source_label,
                write_index=write_index,
            )

            all_images.extend(result.images)
            all_diagrams.extend(result.diagrams)

        logger.info("qti_export_complete exams=%d images=%d", len(export.exams), len(all_images))
        return IngestResult(
            markdown="", images=all_images, diagrams=all_diagrams, source_format="qti"
        )
    finally:
        if export.is_temp:
            shutil.rmtree(export.root, ignore_errors=True)
