"""Normalized quiz model → LLM-friendly markdown.

One quiz renders as an H1 title + a metadata line + instructions, then the
questions as **`## Question N` headings**. The exam title is the only `#`
H1, so the per-exam splitter cuts one document per quiz; the `##` question
headings let the markdown be re-split per question (and chunked by QMD)
without custom parsing.

Each question states its correct answer(s) both inline (a `✓` on the
option) and as an explicit `**Correct answer:**` line, so the answer is
retrievable as text without parsing the options — what a RAG consumer
needs. `answer_key=False` renders a blank quiz (no marks, no answer lines).
"""

from __future__ import annotations

import string

from ..models._quiz import Quiz, QuizQuestion

_LETTERS = string.ascii_uppercase

_TYPE_LABEL = {
    "multiple_choice_question": "Multiple choice",
    "true_false_question": "True/False",
    "multiple_answers_question": "Multiple answers",
    "matching_question": "Matching",
    "short_answer_question": "Fill in the blank",
    "fill_in_multiple_blanks_question": "Fill in multiple blanks",
    "essay_question": "Essay",
}


def _num(x: float) -> str:
    """Format a points number without a trailing `.0` (100.0 -> '100')."""
    return f"{x:g}"


def _fmt_points(p: float) -> str:
    return f"{_num(p)} {'pt' if p == 1 else 'pts'}"


def _type_label(qtype: str) -> str:
    if qtype in _TYPE_LABEL:
        return _TYPE_LABEL[qtype]
    return qtype.removesuffix("_question").replace("_", " ").capitalize()


def _letter(i: int) -> str:
    return _LETTERS[i] if i < len(_LETTERS) else str(i + 1)


def _render_choice_body(q: QuizQuestion, answer_key: bool, *, multi: bool) -> str:
    lines: list[str] = []
    correct: list[str] = []
    for i, opt in enumerate(q.options):
        letter = _letter(i)
        mark = " ✓" if (answer_key and opt.is_correct) else ""
        lines.append(f"- {letter}. {opt.text_md}{mark}")
        if opt.is_correct:
            correct.append(f"{letter}. {opt.text_md}")
    if answer_key and correct:
        label = "Correct answers" if multi else "Correct answer"
        lines.append("")
        lines.append(f"**{label}:** {'; '.join(correct)}")
    return "\n".join(lines)


def _render_matching_body(q: QuizQuestion, answer_key: bool) -> str:
    if answer_key:
        lines = ["| Item | Correct match |", "|---|---|"]
        lines += [f"| {left} | {right} |" for left, right in q.matches]
        return "\n".join(lines)
    lines = ["Items:"]
    lines += [f"- {left}" for left, _ in q.matches]
    pool: list[str] = []
    for _, right in q.matches:
        if right and right not in pool:
            pool.append(right)
    if pool:
        lines.append("")
        lines.append("Match with:")
        lines += [f"- {r}" for r in pool]
    return "\n".join(lines)


def _render_fib_body(q: QuizQuestion, answer_key: bool) -> str:
    if not answer_key:
        return ""
    pairs = [f"{name} = {' / '.join(texts)}" for name, texts in q.blanks.items()]
    return f"**Answers:** {'; '.join(pairs)}" if pairs else ""


def _render_short_body(q: QuizQuestion, answer_key: bool) -> str:
    if not answer_key or not q.accepted:
        return ""
    return f"**Accepted answer(s):** {' / '.join(q.accepted)}"


def _render_body(q: QuizQuestion, answer_key: bool) -> str:
    t = q.qtype
    if t in ("multiple_choice_question", "true_false_question"):
        return _render_choice_body(q, answer_key, multi=False)
    if t == "multiple_answers_question":
        return _render_choice_body(q, answer_key, multi=True)
    if t == "matching_question":
        return _render_matching_body(q, answer_key)
    if t == "fill_in_multiple_blanks_question":
        return _render_fib_body(q, answer_key)
    if t == "short_answer_question":
        return _render_short_body(q, answer_key)
    if t == "essay_question":
        return ""
    # unknown type: show choices if the parser recovered any
    return _render_choice_body(q, answer_key, multi=False) if q.options else ""


def _render_question(q: QuizQuestion, position: int, answer_key: bool) -> str:
    # `## Question N` heading (not a bold block) so the doc is edit-friendly
    # and re-splits per question by a plain heading split — which also lets a
    # markdown chunker (QMD) chunk per question. The exam title stays the only
    # `#` H1, so the per-exam splitter is unaffected. `position` (document
    # order) drives the number so a re-render always normalizes to 1..N.
    parts = [
        f"## Question {position}",
        "",
        f"_{_type_label(q.qtype)} · {_fmt_points(q.points)}_",
        "",
    ]
    if q.stem_md.strip():
        parts.append(q.stem_md.strip())
    body = _render_body(q, answer_key)
    if body:
        parts.append("")
        parts.append(body)
    return "\n".join(parts).strip()


def render_quiz(quiz: Quiz, *, answer_key: bool = True) -> str:
    """Render one quiz as markdown (H1 title + `## Question N` blocks)."""
    lines = [f"# {quiz.title}", ""]
    lines.append(f"_{len(quiz.questions)} questions · {_num(quiz.points_possible)} points_")
    lines.append("")
    if quiz.instructions_md.strip():
        lines.append(quiz.instructions_md.strip())
        lines.append("")
    blocks = [_render_question(q, i, answer_key) for i, q in enumerate(quiz.questions, 1)]
    lines.append("\n\n".join(blocks))  # `## Question N` headings delimit — no `---`
    return "\n".join(lines).rstrip() + "\n"


def render_quizzes(quizzes: list[Quiz], *, answer_key: bool = True) -> str:
    """Render multiple quizzes into one combined markdown document, H1 per quiz."""
    return "\n\n".join(render_quiz(q, answer_key=answer_key).rstrip() for q in quizzes) + "\n"
