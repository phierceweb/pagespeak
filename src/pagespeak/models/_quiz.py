"""Normalized quiz model — the intermediate representation between the QTI
parser and the markdown renderer.

Parse-then-render: `backends/_qti_parse` produces these frozen value
objects from Canvas QTI XML; `backends/_qti_render` turns them into
markdown. Keeping a clean model in the middle is what lets the same engine
later emit a blank version, an answer key, or JSON for a RAG pipeline
without touching the parser.

A `QuizQuestion` carries one populated collection per question *type*:
multiple-choice / true-false / multiple-answers use `options`; matching
uses `matches`; fill-in-multiple-blanks uses `blanks`; short-answer uses
`accepted`; essay uses none (prompt only). Unused collections stay empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QuizOption:
    """One selectable choice in a multiple-choice / true-false /
    multiple-answers question.

    Attributes:
        text_md: The option text, as cleaned markdown.
        is_correct: Whether this option is (part of) the correct answer.
        ident: The original QTI answer id (provenance / debugging).
    """

    text_md: str
    is_correct: bool
    ident: str


@dataclass(frozen=True)
class QuizQuestion:
    """One question, type-agnostic at the container level.

    Attributes:
        number: Our sequential 1..N position (Canvas item titles are
            inconsistent, so we number ourselves).
        qtype: The Canvas `question_type` string.
        points: Points possible for this question.
        stem_md: The question stem as cleaned markdown (images resolved,
            equations as inline LaTeX).
        options: Choices for choice-style questions.
        matches: `(left, correct_right)` pairs for matching questions.
        blanks: `blank_name -> accepted answers` for fill-in-multiple-blanks.
        accepted: Accepted texts for a single-blank short-answer question.
        image_refs: Image basenames referenced by the stem.
    """

    number: int
    qtype: str
    points: float
    stem_md: str
    options: list[QuizOption] = field(default_factory=list)
    matches: list[tuple[str, str]] = field(default_factory=list)
    blanks: dict[str, list[str]] = field(default_factory=dict)
    accepted: list[str] = field(default_factory=list)
    image_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Quiz:
    """One quiz / exam parsed from a QTI assessment.

    Attributes:
        title: The quiz title (from `assessment_meta.xml`).
        points_possible: Total points for the quiz.
        instructions_md: Cleaned markdown of the quiz description /
            instructions block.
        questions: The questions, in document order.
    """

    title: str
    points_possible: float
    instructions_md: str = ""
    questions: list[QuizQuestion] = field(default_factory=list)
