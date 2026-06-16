"""Tests for the Top Hat quiz PDF backend (`backends/_tophat.py`).

The Top Hat web-print PDF has a clean text layer that Marker/Docling damage
with layout-table inference. This backend reads the text layer directly,
strips web chrome, and promotes each `Question N` marker to a `## Question N`
heading so the normal pipeline splits one file per question.

Most tests run on `list[str]` line fixtures (the shape `extract_lines`
returns) and need no PDF / pypdfium2 — only the extract path does, so the
module is gated per-test, not whole-module.
"""

from __future__ import annotations

from pagespeak.backends import _tophat, _tophat_answers, _tophat_parse, _tophat_render
from pagespeak.models._models import IngestResult

# A synthetic slice of a Top Hat text layer (reading order across pages),
# including the interleaved "Video" placeholder blocks that split an option
# list across a page break (Q1's B-E follow a Video block).
SAMPLE_LINES = [
    "Using AI for Learning",
    "Use this free, assignable module to set expectations with your students",
    "course.",
    "Learn More",
    "Responses",
    "Sample_Quiz_2 (53m)",
    "Closed",
    "Exported for Jordan Rivers on Sun, 07 Jun 2026 19:52:09 GMT",
    "Video",
    "Please visit the textbook on a web or",
    "mobile device to view video content.",
    "Module 9:",
    "Hydraulics Widgetry",
    "Page 2:",
    "Your guided lecture notes/study guide for this material are here, in a google doc.",
    "DO: Watch the videos and answer the questions, when presented.",
    "Sample 2 Question 1 Show Correct Answer Show Responses",
    "Which of the following will cause an increase in the metric?",
    "A the first option",
    # --- page break: Q1's remaining options sit after a Video block ---
    "Video",
    "Please visit the textbook on a web or",
    "mobile device to view video content.",
    "B stronger primary contraction",
    "C increased secondary contractility",
    "D all of the above",
    "E A and B",
    "Sample 2 Question 2 Show Correct Answer Show Responses",
    "Which of these phrases accurately describes the governing law?",
    "A Increased input pressure decreases output volume.",
    "B Increased the metric tends to increase output volume.",
    # an option that wraps onto a second line:
    "C As the first option increases, the segments stretch and increase",
    "the force of contraction.",
]


def test_strip_chrome_removes_banner_video_and_ui_tokens() -> None:
    out = _tophat_parse.strip_chrome(SAMPLE_LINES)
    joined = "\n".join(out)
    assert "Using AI for Learning" not in out
    assert "Learn More" not in out
    assert "Video" not in out
    assert "Responses" not in out  # bare UI token line dropped
    assert "Please visit the textbook on a web or" not in joined
    # but the question marker line (which CONTAINS "Show Responses") survives
    assert any("Sample 2 Question 1" in ln for ln in out)


def test_looks_like_tophat_true_on_markered_lines() -> None:
    assert _tophat_parse.looks_like_tophat(SAMPLE_LINES) is True


def test_looks_like_tophat_false_on_ordinary_text() -> None:
    assert _tophat_parse.looks_like_tophat(["# Some manual", "Chapter 1", "body text"]) is False


def test_looks_like_tophat_true_on_hide_correct_answer() -> None:
    # answers-populated exports say "Hide Correct Answer", not "Show"
    lines = ["Optical Question 2 Hide Correct Answer Show Responses", "A x", "B y"]
    assert _tophat_parse.looks_like_tophat(lines) is True


# Some quizzes number questions WITHOUT the word "Question" — the marker is
# "<prefix> <N> (Show|Hide) Correct Answer" (e.g. "Pneumatic 2 Hide …").
NO_QUESTION_WORD_LINES = [
    "Pneumatic_1",
    "Module 12:",
    "Pneumatic system",
    "Pneumatic 1",  # discussion (bare, no answer toggle) → dropped
    "Pneumatic 2 Hide Correct Answer Show Responses",
    "Which of these is the most accurate statement?",
    "A Widgets are produced to attack markers.",
    "B Markers are produced to attack widgets.",
    "Pneumatic 3 Hide Correct Answer Show Responses",
    "Identify the structure indicated.",
    "A primary node",
    "B secondary node",
]


def test_strip_chrome_truncates_trailing_footer() -> None:
    # The instructor "work ahead / playlist" footer trails the last question and
    # must NOT be absorbed into the last option. strip_chrome cuts at it.
    lines = [
        "Toolcraft Terms 1 Question 9 Hide Correct Answer Show Responses",
        "Which divider separates front and back?",
        "E fifth divider",
        "WANT TO WORK AHEAD?",
        "WATCH THE REMAINING LECTURE VIDEOS ON THIS TOPIC. The titles correspond to headings in",
        "your notes.",
        "HERE'S THE PLAYLIST! IT FOLLOWS THE ORDER OF THE NOTES.",
    ]
    out = _tophat_parse.strip_chrome(lines)
    assert out[-1] == "E fifth divider"
    assert not any("PLAYLIST" in ln or "WORK AHEAD" in ln or "your notes" in ln for ln in out)


def test_strip_chrome_truncates_playlist_for_this_topic_footer() -> None:
    lines = ["E fifth option", "PLAYLIST FOR THIS TOPIC."]
    assert _tophat_parse.strip_chrome(lines) == ["E fifth option"]


def test_parse_quiz_last_option_excludes_footer() -> None:
    quiz = _tophat_parse.parse_quiz(
        [
            "Toolcraft Terms 1 Question 9 Hide Correct Answer Show Responses",
            "Which divider separates front and back?",
            "A first divider",
            "B second divider",
            "C third divider",
            "D fourth divider",
            "E fifth divider",
            "WANT TO WORK AHEAD?",
            "HERE'S THE PLAYLIST! IT FOLLOWS THE ORDER OF THE NOTES.",
        ]
    )
    opts = dict(quiz.questions[0].options)
    assert opts["E"] == "fifth divider"  # footer not appended


def test_looks_like_tophat_true_without_question_word() -> None:
    assert _tophat_parse.looks_like_tophat(["Pneumatic 2 Hide Correct Answer Show Responses"])


def test_parse_quiz_handles_no_question_word_marker() -> None:
    quiz = _tophat_parse.parse_quiz(NO_QUESTION_WORD_LINES)
    # the number before "(Show|Hide) Correct Answer" is the question number;
    # the bare "Pneumatic 1" discussion (no toggle) is dropped.
    assert [q.number for q in quiz.questions] == [2, 3]
    q2 = quiz.questions[0]
    assert q2.stem == "Which of these is the most accurate statement?"
    assert [letter for letter, _ in q2.options] == ["A", "B"]


# Lone-letter options whose text wraps across following lines (Q5 shape).
MULTILINE_OPTION_LINES = [
    "Optical Question 5 Hide Correct Answer Show Responses",
    "Which sequence restores equilibrium?",
    "A",
    "The first stage emits the-output then the second stage converts Alpha I",
    "to Alpha II",
    "B",
    "The sensor cells emit the modulator",
]


def test_parse_quiz_handles_lone_letter_multiline_options() -> None:
    quiz = _tophat_parse.parse_quiz(MULTILINE_OPTION_LINES)
    q = quiz.questions[0]
    assert q.number == 5
    assert q.stem == "Which sequence restores equilibrium?"
    opts = dict(q.options)
    assert set(opts) == {"A", "B"}
    assert opts["A"] == (
        "The first stage emits the-output then the second stage converts Alpha I to Alpha II"
    )
    assert opts["B"] == "The sensor cells emit the modulator"


def test_parse_quiz_stem_starting_with_capital_letter_is_not_an_option() -> None:
    # Regression: a stem beginning "A device reports…" must NOT be parsed as
    # option A. Real options run sequentially A,B,C,…; the stray leading A
    # resets to the genuine option run.
    lines = [
        "Optical Question 5 Hide Correct Answer Show Responses",
        "A device reports a low reading. Which sequence occurs?",
        "A",
        "The first stage emits the-output then the second stage makes Alpha II",
        "B",
        "The sensor cells emit the modulator",
        "C",
        "The inhibitor blocks the-output",
        "D",
        "The downstream unit releases the-output",
    ]
    q = _tophat_parse.parse_quiz(lines).questions[0]
    assert q.stem == "A device reports a low reading. Which sequence occurs?"
    assert [letter for letter, _ in q.options] == ["A", "B", "C", "D"]
    assert q.options[0] == (
        "A",
        "The first stage emits the-output then the second stage makes Alpha II",
    )
    # no duplicate A, stem not leaked into options
    assert sum(1 for letter, _ in q.options if letter == "A") == 1


# Fill-in-the-blank questions: stem sentence, answer value(s), then Top Hat's
# `blankN` / `BlankN` placeholder-label lines (noise).
FITB_SINGLE = [
    "Thermal 1 Question 13 Hide Correct Answer Show Responses",
    "The fault caused by oversupply of the driver in the late stage is .",
    "widget",
    "blank1",
    "Blank1",
]
FITB_MULTI = [
    "Optical Question 3 Hide Correct Answer Show Responses",
    "Intake at the node occurs from the to the . Use structural names",
    "for node parts, not flows.",
    "primary chamber",
    "primary channels",
    "blank1 blank2",
    "Blank1 Blank2",
]


def test_parse_quiz_fill_in_the_blank_single() -> None:
    q = _tophat_parse.parse_quiz(FITB_SINGLE).questions[0]
    assert q.number == 13
    assert q.options == []
    assert q.blanks == ("widget",)
    # the trailing blank gap is marked, label noise is gone
    assert q.stem.endswith("is ______.")
    assert "blank1" not in q.stem.lower()


def test_parse_quiz_fill_in_the_blank_multi() -> None:
    q = _tophat_parse.parse_quiz(FITB_MULTI).questions[0]
    assert q.blanks == ("primary chamber", "primary channels")
    # both stem lines (sentence wraps to the period) are the stem; answers excluded
    assert q.stem.startswith("Intake at the node")
    assert "not flows." in q.stem
    assert "primary chamber" not in q.stem


def test_render_fill_in_the_blank_marks_answer_and_drops_labels() -> None:
    md = _tophat_render.render_quiz(_tophat_parse.parse_quiz(FITB_SINGLE))
    assert "**Answer:** widget" in md
    assert "Blank1" not in md
    assert "blank1" not in md


def test_parse_quiz_fill_in_the_blank_inline_template_layout() -> None:
    # Layout B: a template line with INLINE blank tokens, then the pure label
    # line, then the answer. The blank tokens must NOT leak into the answer.
    lines = [
        "Widget 2 Question 14 Hide Correct Answer Show Responses",
        "Identify the part by its function. Correct spelling required.",
        "blank2 blank1 pushes the lever forward and shifts the plate.",
        "Blank2 Blank1",
        "actuator",
    ]
    q = _tophat_parse.parse_quiz(lines).questions[0]
    assert q.blanks == ("actuator",)
    assert "blank" not in q.stem.lower()  # no blankN tokens leak into the stem
    assert "______" in q.stem  # inline blanks marked as gaps
    assert "pushes the lever forward" in q.stem  # the template clue is preserved


def test_render_fill_in_the_blank_multi_uses_plural() -> None:
    md = _tophat_render.render_quiz(_tophat_parse.parse_quiz(FITB_MULTI))
    assert "**Answers:** primary chamber; primary channels" in md


def test_parse_quiz_extracts_title_subtitle_and_export() -> None:
    quiz = _tophat_parse.parse_quiz(SAMPLE_LINES)
    assert quiz.title == "Sample_Quiz_2 (53m)"
    assert quiz.subtitle is not None
    assert "Module 9:" in quiz.subtitle
    assert "Hydraulics Widgetry" in quiz.subtitle
    # DO: instructions and the google-doc line are NOT part of the subtitle
    assert "guided lecture" not in quiz.subtitle
    assert "Watch the videos" not in quiz.subtitle
    assert quiz.exported is not None and "Jordan Rivers" in quiz.exported


def test_parse_quiz_segments_all_questions() -> None:
    quiz = _tophat_parse.parse_quiz(SAMPLE_LINES)
    assert [q.number for q in quiz.questions] == [1, 2]
    q1 = quiz.questions[0]
    assert q1.stem == "Which of the following will cause an increase in the metric?"
    assert [letter for letter, _ in q1.options] == ["A", "B", "C", "D", "E"]
    assert q1.options[0] == ("A", "the first option")
    # cross-page option (E) was recovered after the interleaved Video block
    assert q1.options[-1] == ("E", "A and B")


def test_parse_quiz_joins_wrapped_option_text() -> None:
    quiz = _tophat_parse.parse_quiz(SAMPLE_LINES)
    q2 = quiz.questions[1]
    c_text = dict(q2.options)["C"]
    assert c_text == (
        "As the first option increases, the segments stretch and increase the force of contraction."
    )


def test_render_quiz_has_one_h1_and_h2_questions() -> None:
    quiz = _tophat_parse.parse_quiz(SAMPLE_LINES)
    md = _tophat_render.render_quiz(quiz)
    assert md.count("\n# ") + md.startswith("# ") == 1  # exactly one H1
    assert "# Sample_Quiz_2 (53m)" in md
    assert "## Question 1" in md
    assert "## Question 2" in md
    assert "- A. the first option" in md
    assert "> Module 9:" in md


def test_render_quiz_no_answer_lines_without_answers() -> None:
    # No answers passed → render is questions-only, no fabricated answer.
    md = _tophat_render.render_quiz(_tophat_parse.parse_quiz(SAMPLE_LINES))
    assert "Correct answer" not in md
    assert "✓" not in md


def test_render_quiz_marks_correct_answer_when_provided() -> None:
    quiz = _tophat_parse.parse_quiz(SAMPLE_LINES, {1: ["E"], 2: ["D"]})
    md = _tophat_render.render_quiz(quiz)
    assert "- E. A and B ✓" in md
    assert "**Correct answer:** E. A and B" in md
    # only the correct option is marked
    assert "- A. the first option ✓" not in md


def test_parse_quiz_includes_bare_figure_question() -> None:
    # A bare marker ("… Question 1" with no answer toggle) is kept ONLY when it
    # has a figure; rendered as a heading + image, no options.
    lines = [
        "Thermal 1, page 1 (69m)",
        "Module 5:",
        "Thermal 1 Question 1",  # bare marker (no "Correct Answer")
        "Thermal 1 Question 2 Hide Correct Answer Show Responses",
        "Which agent is heat-stable?",
        "A alpha",
        "B beta",
    ]
    quiz = _tophat_parse.parse_quiz(lines, {2: ["B"]}, {1: ["images/q1_1.png"]})
    nums = [q.number for q in quiz.questions]
    assert nums == [1, 2]  # figure Q1 kept, Q2 kept
    q1 = quiz.questions[0]
    assert q1.images == ("images/q1_1.png",)
    assert q1.options == []


def test_parse_quiz_drops_bare_marker_without_figure() -> None:
    # A bare discussion marker with no figure is not a question.
    lines = [
        "Optical_1 (77m)",
        "Optical Question 1",  # discussion, no answer toggle, no image
        "Optical Question 2 Hide Correct Answer Show Responses",
        "Recovery occurs where?",
        "A primary chamber",
        "B channel",
    ]
    quiz = _tophat_parse.parse_quiz(lines, {2: ["B"]}, {})
    assert [q.number for q in quiz.questions] == [2]


def test_render_quiz_emits_image_ref_for_figure_question() -> None:
    q = _tophat.TopHatQuestion(
        number=1, stem="", options=[], correct=(), images=("images/q1_1.png",)
    )
    quiz = _tophat.TopHatQuiz(title="Sample", subtitle=None, exported=None, questions=[q])
    md = _tophat_render.render_quiz(quiz)
    assert "## Question 1" in md
    assert "![](images/q1_1.png)" in md


def test_render_quiz_emits_question_type_line() -> None:
    # the `_<type>_` line drives both human readability and the question_type
    # frontmatter the splitter reads.
    mc = _tophat.TopHatQuestion(1, "Q?", [("A", "x"), ("B", "y")], correct=("A",))
    fib = _tophat.TopHatQuestion(2, "Q?", [], blanks=("ans",))
    multi = _tophat.TopHatQuestion(3, "Q?", [("A", "x"), ("B", "y")], correct=("A", "B"))
    img = _tophat.TopHatQuestion(4, "", [], images=("images/q4_1.png",))
    quiz = _tophat.TopHatQuiz("T", None, None, [mc, fib, multi, img])
    md = _tophat_render.render_quiz(quiz)
    assert "_Multiple choice_" in md
    assert "_Fill in the blank_" in md
    assert "_Multiple answers_" in md
    assert "_Image_" in md


def test_render_quiz_multi_answer_uses_plural_label() -> None:
    quiz = _tophat_parse.parse_quiz(SAMPLE_LINES, {1: ["A", "B"]})
    md = _tophat_render.render_quiz(quiz)
    assert "**Correct answers:**" in md
    assert "A. the first option; B. stronger primary contraction" in md


def test_convert_pdf_tophat_returns_question_markdown(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_tophat, "extract_lines", lambda _p: SAMPLE_LINES)
    monkeypatch.setattr(_tophat_answers, "extract_correct_answers", lambda _p: {})
    result = _tophat.convert_pdf_tophat(tmp_path / "quiz.pdf")
    assert isinstance(result, IngestResult)
    assert "## Question 1" in result.markdown
    assert result.images == []  # v1 is text-only
    assert result.source_format == "pdf"


def test_convert_pdf_tophat_marks_correct_answers(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_tophat, "extract_lines", lambda _p: SAMPLE_LINES)
    monkeypatch.setattr(_tophat_answers, "extract_correct_answers", lambda _p: {1: ["E"], 2: ["D"]})
    md = _tophat.convert_pdf_tophat(tmp_path / "quiz.pdf").markdown
    assert "- E. A and B ✓" in md
    assert "**Correct answer:** E. A and B" in md
    # (E option "A and B" is structural, not corpus content — kept)


def test_convert_pdf_tophat_rejects_non_tophat(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_tophat, "extract_lines", lambda _p: ["# Manual", "body"])
    try:
        _tophat.convert_pdf_tophat(tmp_path / "manual.pdf")
    except ValueError as e:
        assert "Top Hat" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for a non-Top-Hat PDF")
