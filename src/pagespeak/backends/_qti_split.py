"""QTI per-question split + output frontmatter.

Splits one exam's rendered markdown into one self-contained `Question NNN.md`
per question (each with rich provenance frontmatter for RAG linkage), and
builds the whole-exam master doc's frontmatter. Kept separate from
`backends/_qti` (discovery + per-exam ingest) to stay under the per-module
size budget.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..services._provenance import build_frontmatter
from ..services._split import _clear_prior_split

_QUESTION_RE = re.compile(r"^## Question (\d+)\b")
# The per-question metadata italic line: `_<type>_` or `_<type> · <points>_`
# (Top Hat quizzes carry no points, so the ` · <points>` half is optional).
_TYPE_LINE_RE = re.compile(r"^_(.+?)(?: · (.+?))?_$")


def _doc_title(markdown: str) -> str:
    """The document's first `# ` H1 (the quiz title), or 'Quiz' if none."""
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Quiz"


def _slug(text: str) -> str:
    """A filename/id-safe slug of `text` (lowercase, non-alnum → hyphen)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def exam_frontmatter(
    *,
    course: str,
    exam_title: str,
    quiz_id: str,
    points_possible: float,
    question_count: int,
    source_type: str | None,
    source_label: str | None,
) -> str:
    """Provenance frontmatter for an exam's whole-document master file."""
    return build_frontmatter(
        {
            "source_type": source_type or "quiz",
            "source_label": source_label or course or None,
            "course": course or None,
            "exam": exam_title,
            "quiz_id": quiz_id or None,
            "points_possible": points_possible,
            "question_count": question_count,
        }
    )


def _rewrite_images_up_one(body: str) -> str:
    """`images/…` → `../images/…` so a `sections/Question NNN.md` resolves to
    the exam's `images/` (one level up)."""
    return body.replace("](images/", "](../images/").replace(
        'pagespeak-image="images/', 'pagespeak-image="../images/'
    )


def split_quiz_into_questions(
    exam_md: str,
    sections_dir: str | Path,
    *,
    course: str,
    exam_title: str,
    quiz_id: str,
    source_type: str | None,
    source_label: str | None,
    write_index: bool = True,
    title_field: str = "exam",
) -> list[Path]:
    """Split one exam's markdown into one `Question NNN.md` per question.

    Splits on the `## Question N` headings (the exam title is the only `#`
    H1, and any pre-Q1 preamble/instructions stay in the master doc). Each
    file gets rich frontmatter (course / exam / quiz_id + question_number /
    type / points) and its image refs rewritten to `../images/…`. Writes an
    `INDEX.md` when `write_index` (default True). Returns the written paths.
    """
    sections = Path(sections_dir)
    sections.mkdir(parents=True, exist_ok=True)
    # Clear the prior render: no surplus files from a shrunk re-export, no
    # stale case-variant capturing a fresh write's name.
    _clear_prior_split(sections)

    blocks: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    number = 0
    for line in exam_md.splitlines():
        m = _QUESTION_RE.match(line)
        if m:
            if current is not None:
                blocks.append((number, current))
            number = int(m.group(1))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append((number, current))

    written: list[Path] = []
    index: list[tuple[int, str]] = []
    for num, buf in blocks:
        qtype = points = ""
        for ln in buf:
            tm = _TYPE_LINE_RE.match(ln.strip())
            if tm:
                qtype, points = tm.group(1).strip(), (tm.group(2) or "").strip()
                break
        body = _rewrite_images_up_one("\n".join(buf).strip())
        fields: dict[str, object] = {
            "source_type": source_type or "quiz",
            "source_label": source_label or course or None,
            "course": course or None,
            title_field: exam_title,
            "quiz_id": quiz_id or None,
            "question_number": num,
            "question_type": qtype or None,
            "points": points or None,
        }
        front = build_frontmatter(fields)
        fname = f"Question {num:03d}.md"
        (sections / fname).write_text(front + body + "\n", encoding="utf-8")
        written.append(sections / fname)
        index.append((num, fname))

    if write_index and index:
        lines = [f"# Questions — {exam_title}", ""]
        # Angle-wrap the target — `fname` is "Question NNN.md" (has a space), so a
        # bare `](Question 001.md)` would render as literal text, not a link.
        lines += [f"- [Question {n}](<{fname}>)" for n, fname in index]
        (sections / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def quiz_master_frontmatter(
    markdown: str, *, source_type: str | None, source_label: str | None, source_file: str
) -> str:
    """Quiz-level provenance for the whole-doc master file (a Top Hat quiz).

    Derives `quiz` + `quiz_id` from the document's `# ` title and counts the
    `## Question N` blocks. Lean by design — no course / points (a Top Hat
    export carries neither)."""
    title = _doc_title(markdown)
    count = sum(1 for ln in markdown.splitlines() if _QUESTION_RE.match(ln))
    return build_frontmatter(
        {
            "source_type": source_type or "quiz",
            "source_label": source_label or None,
            "source_file": source_file,
            "quiz": title,
            "quiz_id": _slug(title),
            "question_count": count,
        }
    )


def split_quiz_doc(
    markdown: str,
    sections_dir: str | Path,
    *,
    source_type: str | None,
    source_label: str | None,
) -> list[Path]:
    """Split a single Top Hat quiz doc into rich per-question section files.

    The generic-pipeline counterpart to `split_quiz_into_questions` (which the
    QTI fan-out drives per exam): derives `exam_title`/`quiz_id` from the doc's
    own `# ` title, tags each question `source_type: "quiz"` with a `quiz:`
    title field, and carries no course/points.
    """
    title = _doc_title(markdown)
    return split_quiz_into_questions(
        markdown,
        sections_dir,
        course="",
        exam_title=title,
        quiz_id=_slug(title),
        source_type=source_type or "quiz",
        source_label=source_label,
        title_field="quiz",
    )
