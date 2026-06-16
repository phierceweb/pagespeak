"""Tests for the normalized quiz model dataclasses.

These are plain frozen value objects produced by the QTI parser and
consumed by the renderer. The tests pin frozen-ness (so a parsed quiz
can't be mutated downstream) and the per-type collection defaults (a type
that doesn't use a field gets an empty collection, never None).
"""

from __future__ import annotations

import dataclasses

import pytest

from pagespeak.models._quiz import Quiz, QuizOption, QuizQuestion


def test_quiz_option_is_frozen() -> None:
    opt = QuizOption(text_md="True", is_correct=False, ident="9692")
    with pytest.raises(dataclasses.FrozenInstanceError):
        opt.is_correct = True  # type: ignore[misc]


def test_quiz_question_is_frozen() -> None:
    q = QuizQuestion(number=1, qtype="essay_question", points=5.0, stem_md="Discuss.")
    with pytest.raises(dataclasses.FrozenInstanceError):
        q.points = 1.0  # type: ignore[misc]


def test_question_collection_fields_default_empty() -> None:
    q = QuizQuestion(number=1, qtype="essay_question", points=5.0, stem_md="Discuss.")
    assert q.options == []
    assert q.matches == []
    assert q.blanks == {}
    assert q.accepted == []
    assert q.image_refs == []


def test_question_holds_options() -> None:
    opts = [
        QuizOption(text_md="True", is_correct=False, ident="9692"),
        QuizOption(text_md="False", is_correct=True, ident="9635"),
    ]
    q = QuizQuestion(
        number=2,
        qtype="true_false_question",
        points=1.0,
        stem_md="The PNS always inhibits.",
        options=opts,
    )
    assert len(q.options) == 2
    assert q.options[1].is_correct is True


def test_quiz_defaults() -> None:
    quiz = Quiz(title="Exam 3", points_possible=100.0)
    assert quiz.instructions_md == ""
    assert quiz.questions == []


def test_quiz_holds_questions() -> None:
    q = QuizQuestion(number=1, qtype="multiple_choice_question", points=1.0, stem_md="Q?")
    quiz = Quiz(title="Exam 3", points_possible=100.0, questions=[q])
    assert quiz.questions[0].number == 1
