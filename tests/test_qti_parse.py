"""Tests for the Canvas QTI parser.

One test per question type, built from representative QTI `<item>` shapes.
Fixtures are minimal `<item>` elements wrapped in a `questestinterop`
document so namespace handling is exercised. The load-bearing cases:
multiple-answers `<not>` exclusion, the matching respident→match map,
fill-in-multiple-blanks per-blank answers, and short-answer accepted-text
lists.
"""

from __future__ import annotations

from pagespeak.backends._qti_parse import (
    parse_assessment_meta,
    parse_quiz_items,
)

_NS = 'xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2"'


def test_assessment_meta_non_numeric_points_defaults_zero() -> None:
    """A malformed `points_possible` must not crash; it defaults to 0.0
    (and now logs a warning so the malformed export is diagnosable)."""
    xml = (
        '<quiz xmlns="http://canvas.instructure.com/xsd/cccv1p0">'
        "<title>Q</title><points_possible>ten</points_possible></quiz>"
    )
    _title, points, _instr = parse_assessment_meta(xml)
    assert points == 0.0


def _wrap(item_xml: str) -> str:
    return (
        f"<questestinterop {_NS}><assessment ident='a' title='t'>"
        f"<section ident='root_section'>{item_xml}</section>"
        f"</assessment></questestinterop>"
    )


def _one(item_xml: str, **kwargs: object) -> object:
    items = parse_quiz_items(_wrap(item_xml), **kwargs)  # type: ignore[arg-type]
    assert len(items) == 1
    return items[0]


_MC = """
<item ident="g1" title="Question">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>multiple_choice_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;Predict the response of the &lt;strong&gt;smooth muscle&lt;/strong&gt; to sympathetic stimulation.&lt;/div&gt;</mattext></material>
    <response_lid ident="response1" rcardinality="Single"><render_choice>
      <response_label ident="8086"><material><mattext texttype="text/plain">excitation and contraction.</mattext></material></response_label>
      <response_label ident="6221"><material><mattext texttype="text/plain">inhibition and relaxation.</mattext></material></response_label>
    </render_choice></response_lid>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition continue="No"><conditionvar><varequal respident="response1">6221</varequal></conditionvar><setvar action="Set" varname="SCORE">100</setvar></respcondition>
  </resprocessing>
</item>
"""


def test_multiple_choice_marks_single_correct() -> None:
    q = _one(_MC)
    assert q.qtype == "multiple_choice_question"
    assert q.points == 1.0
    assert q.number == 1
    assert "**smooth muscle**" in q.stem_md
    assert len(q.options) == 2
    by_id = {o.ident: o for o in q.options}
    assert by_id["6221"].is_correct is True
    assert by_id["8086"].is_correct is False


_TF = """
<item ident="g2" title="Question">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>true_false_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;&lt;p&gt;The parasympathetic nervous system always inhibits its target organs.&lt;/p&gt;&lt;/div&gt;</mattext></material>
    <response_lid ident="response1" rcardinality="Single"><render_choice>
      <response_label ident="9692"><material><mattext texttype="text/plain">True</mattext></material></response_label>
      <response_label ident="9635"><material><mattext texttype="text/plain">False</mattext></material></response_label>
    </render_choice></response_lid>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition continue="No"><conditionvar><varequal respident="response1">9635</varequal></conditionvar><setvar action="Set" varname="SCORE">100</setvar></respcondition>
  </resprocessing>
</item>
"""


def test_true_false_marks_correct() -> None:
    q = _one(_TF)
    assert q.qtype == "true_false_question"
    by_text = {o.text_md: o.is_correct for o in q.options}
    assert by_text["False"] is True
    assert by_text["True"] is False


_MA = """
<item ident="g3" title="Question">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>multiple_answers_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;Which neuron(s) release acetylcholine? &lt;img src="$IMS-CC-FILEBASE$/Uploaded%20Media/main-qimg-d3.jpeg" alt="ANS v SNS"&gt;&lt;/div&gt;</mattext></material>
    <response_lid ident="response1" rcardinality="Multiple"><render_choice>
      <response_label ident="8283"><material><mattext texttype="text/plain">Somatic motor neurons</mattext></material></response_label>
      <response_label ident="2112"><material><mattext texttype="text/plain">Preganglionic sympathetic neurons</mattext></material></response_label>
      <response_label ident="2059"><material><mattext texttype="text/plain">Postganglionic sympathetic neurons</mattext></material></response_label>
      <response_label ident="2153"><material><mattext texttype="text/plain">Preganglionic parasympathetic neurons</mattext></material></response_label>
      <response_label ident="7965"><material><mattext texttype="text/plain">Postganglionic parasympathetic neurons</mattext></material></response_label>
    </render_choice></response_lid>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition continue="No"><conditionvar><and>
      <varequal respident="response1">8283</varequal>
      <varequal respident="response1">2112</varequal>
      <not><varequal respident="response1">2059</varequal></not>
      <varequal respident="response1">2153</varequal>
      <varequal respident="response1">7965</varequal>
    </and></conditionvar><setvar action="Set" varname="SCORE">100</setvar></respcondition>
  </resprocessing>
</item>
"""


def test_multiple_answers_excludes_not_wrapped() -> None:
    q = _one(_MA, media_resolver=lambda src: "images/main-qimg-d3.jpeg")
    assert q.qtype == "multiple_answers_question"
    correct = {o.ident for o in q.options if o.is_correct}
    assert correct == {"8283", "2112", "2153", "7965"}
    # the <not>-wrapped option is NOT correct
    assert next(o for o in q.options if o.ident == "2059").is_correct is False


def test_multiple_answers_extracts_image_ref_and_resolves_stem() -> None:
    q = _one(_MA, media_resolver=lambda src: "images/main-qimg-d3.jpeg")
    assert "main-qimg-d3.jpeg" in q.image_refs
    assert "![ANS v SNS](images/main-qimg-d3.jpeg)" in q.stem_md


_MATCHING = """
<item ident="g4" title="30">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>matching_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>4.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;Match the disorder to the description.&lt;/div&gt;</mattext></material>
    <response_lid ident="response_3750">
      <material><mattext texttype="text/plain">poliomyelitis</mattext></material>
      <render_choice>
        <response_label ident="257"><material><mattext>virus that destroys motor neurons</mattext></material></response_label>
        <response_label ident="8377"><material><mattext>genetic degeneration of muscle</mattext></material></response_label>
      </render_choice>
    </response_lid>
    <response_lid ident="response_2979">
      <material><mattext texttype="text/plain">muscular dystrophy</mattext></material>
      <render_choice>
        <response_label ident="257"><material><mattext>virus that destroys motor neurons</mattext></material></response_label>
        <response_label ident="8377"><material><mattext>genetic degeneration of muscle</mattext></material></response_label>
      </render_choice>
    </response_lid>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition><conditionvar><varequal respident="response_3750">257</varequal></conditionvar><setvar varname="SCORE" action="Add">50.00</setvar></respcondition>
    <respcondition><conditionvar><varequal respident="response_2979">8377</varequal></conditionvar><setvar varname="SCORE" action="Add">50.00</setvar></respcondition>
  </resprocessing>
</item>
"""


def test_matching_maps_left_to_correct_right() -> None:
    q = _one(_MATCHING)
    assert q.qtype == "matching_question"
    assert q.points == 4.0
    assert ("poliomyelitis", "virus that destroys motor neurons") in q.matches
    assert ("muscular dystrophy", "genetic degeneration of muscle") in q.matches


_SHORT = """
<item ident="g5" title="Question">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>short_answer_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;The ________ nervous system has sympathetic and parasympathetic branches.&lt;/div&gt;</mattext></material>
    <response_str ident="response1" rcardinality="Single"><render_fib><response_label ident="answer1" rshuffle="No"/></render_fib></response_str>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition continue="No"><conditionvar>
      <varequal respident="response1">autonomic</varequal>
      <varequal respident="response1">visceral motor</varequal>
      <varequal respident="response1">autonomic motor</varequal>
    </conditionvar><setvar action="Set" varname="SCORE">100</setvar></respcondition>
  </resprocessing>
</item>
"""


def test_short_answer_collects_accepted_texts() -> None:
    q = _one(_SHORT)
    assert q.qtype == "short_answer_question"
    assert q.accepted == ["autonomic", "visceral motor", "autonomic motor"]
    assert q.options == []


_FIB = """
<item ident="g6" title="Question">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>fill_in_multiple_blanks_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;CO = [blank1] x [blank2]&lt;/div&gt;</mattext></material>
    <response_lid ident="response_blank1"><material><mattext>blank1</mattext></material><render_choice>
      <response_label ident="4605"><material><mattext texttype="text/plain">heart rate</mattext></material></response_label>
      <response_label ident="6059"><material><mattext texttype="text/plain">HR</mattext></material></response_label>
    </render_choice></response_lid>
    <response_lid ident="response_blank2"><material><mattext>blank2</mattext></material><render_choice>
      <response_label ident="9729"><material><mattext texttype="text/plain">stroke volume</mattext></material></response_label>
      <response_label ident="4576"><material><mattext texttype="text/plain">SV</mattext></material></response_label>
    </render_choice></response_lid>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition><conditionvar><varequal respident="response_blank1">4605</varequal></conditionvar><setvar varname="SCORE" action="Add">50.00</setvar></respcondition>
    <respcondition><conditionvar><varequal respident="response_blank2">9729</varequal></conditionvar><setvar varname="SCORE" action="Add">50.00</setvar></respcondition>
  </resprocessing>
</item>
"""


def test_fill_in_multiple_blanks_per_blank_answers() -> None:
    q = _one(_FIB)
    assert q.qtype == "fill_in_multiple_blanks_question"
    assert q.blanks == {"blank1": ["heart rate"], "blank2": ["stroke volume"]}


_ESSAY = """
<item ident="g7" title="66">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>essay_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>5.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;&lt;p&gt;Tell me something you know well that was not asked.&lt;/p&gt;&lt;/div&gt;</mattext></material>
    <response_str ident="response1" rcardinality="Single"><render_fib><response_label ident="answer1" rshuffle="No"/></render_fib></response_str>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes>
    <respcondition continue="No"><conditionvar><other/></conditionvar></respcondition>
  </resprocessing>
</item>
"""


def test_essay_has_prompt_no_answers() -> None:
    q = _one(_ESSAY)
    assert q.qtype == "essay_question"
    assert q.points == 5.0
    assert "Tell me something you know well" in q.stem_md
    assert q.options == []
    assert q.accepted == []
    assert q.blanks == {}


_UNKNOWN = """
<item ident="g8" title="Question">
  <itemmetadata><qtimetadata>
    <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>numerical_question</fieldentry></qtimetadatafield>
    <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>2.0</fieldentry></qtimetadatafield>
  </qtimetadata></itemmetadata>
  <presentation>
    <material><mattext texttype="text/html">&lt;div&gt;What is the resting heart rate in bpm?&lt;/div&gt;</mattext></material>
  </presentation>
  <resprocessing><outcomes><decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/></outcomes></resprocessing>
</item>
"""


def test_unknown_type_keeps_stem_without_crashing() -> None:
    q = _one(_UNKNOWN)
    assert q.qtype == "numerical_question"
    assert "resting heart rate" in q.stem_md


def test_parse_quiz_items_numbers_sequentially() -> None:
    doc = _wrap(_MC + _TF + _ESSAY)
    items = parse_quiz_items(doc)
    assert [q.number for q in items] == [1, 2, 3]


_META = """<?xml version="1.0" encoding="UTF-8"?>
<quiz identifier="gf90" xmlns="http://canvas.instructure.com/xsd/cccv1p0">
  <title>Exam 3: Topics A, B, and C</title>
  <description>&lt;h3&gt;For multiple choice questions: choose the best answer.&lt;/h3&gt;&lt;p&gt;Good luck.&lt;/p&gt;</description>
  <points_possible>100.0</points_possible>
  <assignment identifier="g0e"><title>Exam 3 assignment</title><points_possible>100.0</points_possible></assignment>
</quiz>
"""


def test_parse_assessment_meta_title_points_instructions() -> None:
    title, points, instructions = parse_assessment_meta(_META)
    assert title == "Exam 3: Topics A, B, and C"
    assert points == 100.0
    assert "For multiple choice questions: choose the best answer." in instructions
    # instructions <h3> demoted to bold, not an ATX heading
    assert "#" not in instructions
    assert "Good luck." in instructions
