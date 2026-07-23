"""Tests for the QTI per-question split + master-doc frontmatter."""

from __future__ import annotations

from pathlib import Path

from pagespeak.backends._qti_split import (
    exam_frontmatter,
    quiz_master_frontmatter,
    split_quiz_doc,
    split_quiz_into_questions,
)

# A Top Hat quiz doc (no points on the type line; `# title` drives quiz/quiz_id).
_QUIZ_MD = (
    "# Sample Quiz 2\n\n_3 questions_\n\n"
    "## Question 1\n\n_Multiple choice_\n\nWhat is the correct choice?\n\n- A. the first option ✓\n\n"
    "**Correct answer:** A. the first option\n\n"
    "## Question 2\n\n_Fill in the blank_\n\nThe missing word is ______.\n\n**Answer:** widget\n\n"
    "## Question 3\n\n_Image_\n\n![diagram](images/q3_1.png)\n"
)

_EXAM_MD = (
    "# Exam X\n\n_2 questions · 2 points_\n\nInstructions here.\n\n"
    "## Question 1\n\n_Multiple choice · 1 pt_\n\nSee ![cap](images/fig.png)\n\n"
    "- A. x\n- B. y ✓\n\n**Correct answer:** B. y\n\n"
    "## Question 2\n\n_True/False · 1 pt_\n\nThe sky is blue.\n\n- A. True ✓\n- B. False\n"
)


def test_split_writes_one_file_per_question_with_frontmatter(tmp_path: Path) -> None:
    written = split_quiz_into_questions(
        _EXAM_MD,
        tmp_path / "sections",
        course="DEMO-1010",
        exam_title="Exam X",
        quiz_id="gXYZ",
        source_type=None,
        source_label=None,
        write_index=True,
    )
    assert [p.name for p in written] == ["Question 001.md", "Question 002.md"]
    q1 = (tmp_path / "sections" / "Question 001.md").read_text(encoding="utf-8")
    assert q1.startswith("---\n")
    assert 'course: "DEMO-1010"' in q1
    assert 'exam: "Exam X"' in q1
    assert 'quiz_id: "gXYZ"' in q1
    assert "question_number: 1" in q1
    assert 'question_type: "Multiple choice"' in q1
    assert 'points: "1 pt"' in q1
    assert "source_export" not in q1
    assert "## Question 1" in q1
    assert "B. y ✓" in q1
    # image path rewritten relative to sections/
    assert "![cap](../images/fig.png)" in q1
    # the preamble/instructions are NOT a question file
    assert "Instructions here." not in q1
    assert (tmp_path / "sections" / "INDEX.md").exists()
    # The filename has a space ("Question 001.md"), so the INDEX link target must
    # be angle-wrapped — a bare `](Question 001.md)` renders as literal text, not
    # a link (the fix, separately needed in this quiz-split path).
    index = (tmp_path / "sections" / "INDEX.md").read_text(encoding="utf-8")
    assert "[Question 1](<Question 001.md>)" in index
    assert "](Question 001.md)" not in index


def test_split_no_index_and_source_overrides(tmp_path: Path) -> None:
    split_quiz_into_questions(
        _EXAM_MD,
        tmp_path / "sections",
        course="C",
        exam_title="Exam X",
        quiz_id="g",
        source_type="exam",
        source_label="My Label",
        write_index=False,
    )
    assert not (tmp_path / "sections" / "INDEX.md").exists()
    q1 = (tmp_path / "sections" / "Question 001.md").read_text(encoding="utf-8")
    assert 'source_type: "exam"' in q1
    assert 'source_label: "My Label"' in q1


def test_exam_frontmatter_defaults() -> None:
    fm = exam_frontmatter(
        course="DEMO-1010",
        exam_title="Exam 3",
        quiz_id="gABC",
        points_possible=100.0,
        question_count=90,
        source_type=None,
        source_label=None,
    )
    assert 'source_type: "quiz"' in fm  # defaulted
    assert 'source_label: "DEMO-1010"' in fm  # defaults to course
    assert 'exam: "Exam 3"' in fm
    assert "question_count: 90" in fm
    assert "source_export" not in fm


def test_split_quiz_doc_uses_quiz_field_and_derives_id(tmp_path: Path) -> None:
    written = split_quiz_doc(
        _QUIZ_MD,
        tmp_path / "sections",
        source_type="quiz",
        source_label=None,
    )
    assert [p.name for p in written] == [
        "Question 001.md",
        "Question 002.md",
        "Question 003.md",
    ]
    q1 = (tmp_path / "sections" / "Question 001.md").read_text(encoding="utf-8")
    assert 'source_type: "quiz"' in q1
    assert 'quiz: "Sample Quiz 2"' in q1  # the title field is `quiz`, not `exam`
    assert "exam:" not in q1
    assert 'quiz_id: "sample-quiz-2"' in q1  # slug of the H1 title
    assert "question_number: 1" in q1
    assert 'question_type: "Multiple choice"' in q1
    assert "course:" not in q1  # Top Hat carries no course
    assert "points:" not in q1  # …and no points
    # the fill-in-the-blank question's type is captured from its `_..._` line
    q2 = (tmp_path / "sections" / "Question 002.md").read_text(encoding="utf-8")
    assert 'question_type: "Fill in the blank"' in q2


def test_quiz_master_frontmatter_counts_questions() -> None:
    fm = quiz_master_frontmatter(
        _QUIZ_MD, source_type="quiz", source_label=None, source_file="quiz.pdf"
    )
    assert 'source_type: "quiz"' in fm
    assert 'quiz: "Sample Quiz 2"' in fm
    assert 'quiz_id: "sample-quiz-2"' in fm
    assert 'source_file: "quiz.pdf"' in fm
    assert "question_count: 3" in fm


def test_resplit_clears_stale_question_files(tmp_path):
    """A re-render leaves no surplus files from a shrunk re-export, and no
    stale case-variant capturing a fresh write's name."""
    stale_surplus = tmp_path / "Question 099.md"
    stale_surplus.write_text("stale surplus question\n", encoding="utf-8")
    stale_variant = tmp_path / "question 001.md"
    stale_variant.write_text("stale variant\n", encoding="utf-8")

    md = (
        "# Sample Quiz\n\n"
        "## Question 1\n_Multiple choice · 1 pt_\nFresh body one.\n\n"
        "## Question 2\n_Multiple choice · 1 pt_\nFresh body two.\n"
    )
    written = split_quiz_doc(md, tmp_path, source_type=None, source_label=None)
    names = sorted(p.name for p in tmp_path.glob("*.md"))
    assert "Question 099.md" not in names
    assert names == ["INDEX.md", "Question 001.md", "Question 002.md"]
    q1 = (tmp_path / "Question 001.md").read_text(encoding="utf-8")
    assert "Fresh body one." in q1
    assert "stale" not in q1
    assert all(p.exists() for p in written)
