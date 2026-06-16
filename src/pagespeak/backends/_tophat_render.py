"""Parsed Top Hat quiz model → LLM-friendly markdown.

One quiz renders as a `#` H1 title + a metadata line + optional subtitle, then
each question as a `## Question N` heading. The title is the only H1, so the
section splitter cuts one file per question — the same shape as the Canvas QTI
render (`backends/_qti_render`) so Top Hat quizzes and Canvas exams read alike.

When the export revealed the answers (see `_tophat_answers`), the correct
option(s) get a `✓` and an explicit `**Correct answer:**` line so the answer
is retrievable as text without parsing the options. A fill-in-the-blank
question instead renders its answer value(s) on a `**Answer:**` line (from
`q.blanks`). A question with no detected answer (discussion prompt, or a
questions-only export) gets no answer line — the renderer never fabricates one.
"""

from __future__ import annotations

from ._tophat import TopHatQuestion, TopHatQuiz


def _question_type(q: TopHatQuestion) -> str:
    """Classify the question for the metadata line + `question_type` frontmatter."""
    if q.blanks:
        return "Fill in the blank"
    if len(q.correct) > 1:
        return "Multiple answers"
    if q.options:
        return "Multiple choice"
    if q.images:
        return "Image"
    return "Question"


def _render_question(q: TopHatQuestion) -> list[str]:
    """Render one question: heading, type line, stem, options (✓), answer line."""
    out = [f"## Question {q.number}", "", f"_{_question_type(q)}_", ""]
    if q.stem:
        out += [q.stem, ""]
    for img in q.images:
        out += [f"![]({img})", ""]
    correct_texts: list[str] = []
    for letter, text in q.options:
        mark = " ✓" if letter in q.correct else ""
        out.append(f"- {letter}. {text}{mark}".rstrip())
        if letter in q.correct:
            correct_texts.append(f"{letter}. {text}".strip())
    if correct_texts:
        label = "Correct answers" if len(correct_texts) > 1 else "Correct answer"
        out += ["", f"**{label}:** {'; '.join(correct_texts)}"]
    if q.blanks:
        label = "Answers" if len(q.blanks) > 1 else "Answer"
        out += ["", f"**{label}:** {'; '.join(q.blanks)}"]
    out.append("")
    return out


def render_quiz(quiz: TopHatQuiz) -> str:
    """Render a `TopHatQuiz` as markdown: one `#` H1 + `## Question N` blocks."""
    lines: list[str] = [f"# {quiz.title}", ""]
    lines.append(f"_{len(quiz.questions)} questions_")
    lines.append("")
    if quiz.subtitle:
        lines.append(f"> {quiz.subtitle}")
        lines.append("")
    if quiz.exported:
        lines.append(f"_{quiz.exported}_")
        lines.append("")
    for q in quiz.questions:
        lines += _render_question(q)
    return "\n".join(lines).rstrip() + "\n"
