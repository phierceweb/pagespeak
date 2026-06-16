"""Tests for the QTI markdown renderer.

Renders the normalized model to markdown. The load-bearing contracts:
the answer key is correct and retrievable as text (not just a ✓), only the
quiz title is an ATX heading (questions are bold blocks, so the splitter
cuts one file per quiz), and answer_key=False produces a blank quiz.
"""

from __future__ import annotations

from pagespeak.backends._qti_render import render_quiz, render_quizzes
from pagespeak.models._quiz import Quiz, QuizOption, QuizQuestion


def _mc() -> QuizQuestion:
    return QuizQuestion(
        number=1,
        qtype="multiple_choice_question",
        points=1.0,
        stem_md="Predict the response of the smooth muscle.",
        options=[
            QuizOption("excitation and contraction.", False, "8086"),
            QuizOption("inhibition and relaxation.", True, "6221"),
        ],
    )


def test_renders_title_and_header() -> None:
    quiz = Quiz(
        title="Exam 3: Sample Topic",
        points_possible=100.0,
        instructions_md="Choose the best answer.",
        questions=[_mc()],
    )
    out = render_quiz(quiz)
    assert out.startswith("# Exam 3: Sample Topic")
    assert "1 questions · 100 points" in out
    assert "Choose the best answer." in out


def test_multiple_choice_marks_and_states_correct() -> None:
    out = render_quiz(Quiz("E", 1.0, questions=[_mc()]))
    assert "## Question 1" in out
    assert "Multiple choice" in out
    assert "1 pt" in out
    assert "inhibition and relaxation. ✓" in out
    assert "**Correct answer:**" in out
    # the correct text is retrievable from the answer line itself
    assert out.count("inhibition and relaxation.") >= 2


def test_multiple_answers_lists_all_correct() -> None:
    q = QuizQuestion(
        number=1,
        qtype="multiple_answers_question",
        points=1.0,
        stem_md="Which release acetylcholine?",
        options=[
            QuizOption("Somatic motor neurons", False, "a"),
            QuizOption("Preganglionic sympathetic", True, "b"),
            QuizOption("Postganglionic sympathetic", False, "c"),
            QuizOption("Preganglionic parasympathetic", True, "d"),
        ],
    )
    out = render_quiz(Quiz("E", 1.0, questions=[q]))
    assert "Multiple answers" in out
    assert "**Correct answers:**" in out
    assert "Preganglionic sympathetic" in out
    assert "Preganglionic parasympathetic" in out
    assert out.count("✓") == 2


def test_matching_renders_table() -> None:
    q = QuizQuestion(
        number=1,
        qtype="matching_question",
        points=4.0,
        stem_md="Match the disorder to the description.",
        matches=[
            ("poliomyelitis", "virus that destroys motor neurons"),
            ("muscular dystrophy", "genetic degeneration of muscle"),
        ],
    )
    out = render_quiz(Quiz("E", 4.0, questions=[q]))
    assert "Matching" in out
    assert "| poliomyelitis | virus that destroys motor neurons |" in out
    assert "| muscular dystrophy | genetic degeneration of muscle |" in out
    assert "---" in out  # table separator row or hr


def test_fill_in_multiple_blanks_renders_answers() -> None:
    q = QuizQuestion(
        number=1,
        qtype="fill_in_multiple_blanks_question",
        points=1.0,
        stem_md="CO = [blank1] x [blank2]",
        blanks={"blank1": ["heart rate"], "blank2": ["stroke volume"]},
    )
    out = render_quiz(Quiz("E", 1.0, questions=[q]))
    assert "[blank1]" in out
    assert "blank1 = heart rate" in out
    assert "blank2 = stroke volume" in out


def test_short_answer_renders_accepted() -> None:
    q = QuizQuestion(
        number=1,
        qtype="short_answer_question",
        points=1.0,
        stem_md="The ________ nervous system has two branches.",
        accepted=["autonomic", "visceral motor", "autonomic motor"],
    )
    out = render_quiz(Quiz("E", 1.0, questions=[q]))
    assert "Accepted answer" in out
    assert "autonomic" in out
    assert "visceral motor" in out


def test_essay_renders_prompt_only() -> None:
    q = QuizQuestion(
        number=1,
        qtype="essay_question",
        points=5.0,
        stem_md="Tell me something you know well.",
    )
    out = render_quiz(Quiz("E", 5.0, questions=[q]))
    assert "Essay" in out
    assert "Tell me something you know well." in out
    assert "Correct answer" not in out
    assert "✓" not in out


def test_answer_key_false_omits_answers() -> None:
    out = render_quiz(Quiz("E", 1.0, questions=[_mc()]), answer_key=False)
    assert "✓" not in out
    assert "Correct answer" not in out
    # options still rendered (blank quiz)
    assert "excitation and contraction." in out
    assert "inhibition and relaxation." in out


def test_exam_title_is_the_only_h1() -> None:
    quiz = Quiz("Exam 3", 2.0, questions=[_mc(), _mc()])
    out = render_quiz(quiz)
    assert [ln for ln in out.splitlines() if ln.startswith("# ")] == ["# Exam 3"]


def test_questions_render_as_h2_blocks() -> None:
    quiz = Quiz("Exam 3", 2.0, questions=[_mc(), _mc()])
    out = render_quiz(quiz)
    assert [ln for ln in out.splitlines() if ln.startswith("## ")] == [
        "## Question 1",
        "## Question 2",
    ]
    assert "\n---\n" not in out  # headings delimit; no horizontal rules


def test_render_quizzes_combines_with_one_h1_each() -> None:
    quiz_a = Quiz("Quiz A", 1.0, questions=[_mc()])
    quiz_b = Quiz("Quiz B", 1.0, questions=[_mc()])
    out = render_quizzes([quiz_a, quiz_b])
    assert out.count("# Quiz A") == 1
    assert out.count("# Quiz B") == 1
    h1s = [ln for ln in out.splitlines() if ln.startswith("# ")]
    assert h1s == ["# Quiz A", "# Quiz B"]
