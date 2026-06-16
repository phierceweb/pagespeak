"""Tests for the Canvas QTI backend (fan-out model).

Each quiz in an export becomes its own independent full-pipeline document.
This module covers the QTI-specific pieces the fan-out uses: export
discovery (`enumerate_quizzes`), per-exam ingest (`convert_qti_exam` → one
exam's raw markdown + only its figures), and the per-question split
(`split_quiz_into_questions`). The end-to-end fan-out (one export → N
per-exam document dirs) is exercised via `to_markdown`.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from pagespeak.backends._qti import (
    _extract_course,
    _safe_image_name,
    convert_qti_exam,
    enumerate_quizzes,
    is_qti_export,
)

_MANIFEST = """<?xml version="1.0"?>
<manifest identifier="m" xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">
  <metadata><imsmd:lom xmlns:imsmd="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource"><imsmd:general><imsmd:title>
    <imsmd:string>QTI Quiz Export for course "DEMO-1010-001-Fall 2024"</imsmd:string>
  </imsmd:title></imsmd:general></imsmd:lom></metadata>
  <resources>
    <resource identifier="gAAA" type="imsqti_xmlv1p2">
      <file href="gAAA/gAAA.xml"/>
      <dependency identifierref="gAAAmeta"/>
    </resource>
    <resource identifier="gAAAmeta" type="associatedcontent/imscc_xmlv1p1/learning-application-resource" href="gAAA/assessment_meta.xml">
      <file href="gAAA/assessment_meta.xml"/>
    </resource>
    <resource identifier="gBBB" type="imsqti_xmlv1p2">
      <file href="gBBB/gBBB.xml"/>
      <dependency identifierref="gBBBmeta"/>
    </resource>
    <resource identifier="gBBBmeta" type="associatedcontent/imscc_xmlv1p1/learning-application-resource" href="gBBB/assessment_meta.xml">
      <file href="gBBB/assessment_meta.xml"/>
    </resource>
    <resource identifier="figres" type="webcontent" href="web_resources/Uploaded Media/fig.png">
      <file href="web_resources/Uploaded Media/fig.png"/>
    </resource>
  </resources>
</manifest>
"""

_QTI_A = """<questestinterop xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2">
 <assessment ident="gAAA" title="Quiz Alpha"><section ident="root_section">
  <item ident="i1" title="Question">
   <itemmetadata><qtimetadata>
     <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>multiple_choice_question</fieldentry></qtimetadatafield>
     <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
   </qtimetadata></itemmetadata>
   <presentation>
     <material><mattext texttype="text/html">&lt;div&gt;See &lt;img src="$IMS-CC-FILEBASE$/Uploaded%20Media/fig.png" alt="a figure"&gt;. Which is correct?&lt;/div&gt;</mattext></material>
     <response_lid ident="response1" rcardinality="Single"><render_choice>
       <response_label ident="o1"><material><mattext texttype="text/plain">Wrong</mattext></material></response_label>
       <response_label ident="o2"><material><mattext texttype="text/plain">Right</mattext></material></response_label>
     </render_choice></response_lid>
   </presentation>
   <resprocessing><respcondition continue="No"><conditionvar><varequal respident="response1">o2</varequal></conditionvar><setvar action="Set" varname="SCORE">100</setvar></respcondition></resprocessing>
  </item>
 </section></assessment>
</questestinterop>
"""

_META_A = """<?xml version="1.0"?>
<quiz identifier="gAAA" xmlns="http://canvas.instructure.com/xsd/cccv1p0">
  <title>Quiz Alpha</title>
  <description>&lt;p&gt;Answer all questions.&lt;/p&gt;</description>
  <points_possible>10.0</points_possible>
</quiz>
"""

_QTI_B = """<questestinterop xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2">
 <assessment ident="gBBB" title="Quiz Beta"><section ident="root_section">
  <item ident="i1" title="Question">
   <itemmetadata><qtimetadata>
     <qtimetadatafield><fieldlabel>question_type</fieldlabel><fieldentry>true_false_question</fieldentry></qtimetadatafield>
     <qtimetadatafield><fieldlabel>points_possible</fieldlabel><fieldentry>1.0</fieldentry></qtimetadatafield>
   </qtimetadata></itemmetadata>
   <presentation>
     <material><mattext texttype="text/html">&lt;div&gt;The heart has four chambers.&lt;/div&gt;</mattext></material>
     <response_lid ident="response1" rcardinality="Single"><render_choice>
       <response_label ident="t"><material><mattext texttype="text/plain">True</mattext></material></response_label>
       <response_label ident="f"><material><mattext texttype="text/plain">False</mattext></material></response_label>
     </render_choice></response_lid>
   </presentation>
   <resprocessing><respcondition continue="No"><conditionvar><varequal respident="response1">t</varequal></conditionvar><setvar action="Set" varname="SCORE">100</setvar></respcondition></resprocessing>
  </item>
 </section></assessment>
</questestinterop>
"""

_META_B = (
    '<quiz identifier="gBBB" xmlns="http://canvas.instructure.com/xsd/cccv1p0">'
    "<title>Quiz Beta</title><description></description>"
    "<points_possible>5.0</points_possible></quiz>"
)


def _write_export(root: Path) -> None:
    (root / "gAAA").mkdir(parents=True)
    (root / "gAAA" / "gAAA.xml").write_text(_QTI_A, encoding="utf-8")
    (root / "gAAA" / "assessment_meta.xml").write_text(_META_A, encoding="utf-8")
    (root / "gBBB").mkdir(parents=True)
    (root / "gBBB" / "gBBB.xml").write_text(_QTI_B, encoding="utf-8")
    (root / "gBBB" / "assessment_meta.xml").write_text(_META_B, encoding="utf-8")
    media = root / "web_resources" / "Uploaded Media"
    media.mkdir(parents=True)
    (media / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")
    (root / "imsmanifest.xml").write_text(_MANIFEST, encoding="utf-8")


def test_is_qti_export_directory_and_imscc(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    _write_export(export)
    assert is_qti_export(export) is True
    assert is_qti_export(tmp_path / "nope") is False
    imscc = tmp_path / "course.imscc"
    with zipfile.ZipFile(imscc, "w") as zf:
        for f in export.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(export).as_posix())
    assert is_qti_export(imscc) is True


def test_enumerate_quizzes(tmp_path: Path) -> None:
    export = tmp_path / "biol-export"
    export.mkdir()
    _write_export(export)
    qx = enumerate_quizzes(export)
    assert qx.course == "DEMO-1010-001-Fall 2024"
    assert [e.title for e in qx.exams] == ["Quiz Alpha", "Quiz Beta"]
    assert qx.exams[0].quiz_id == "gAAA"
    assert qx.exams[0].points_possible == 10.0
    assert "fig.png" in qx.media
    assert qx.is_temp is False


def test_convert_qti_exam_writes_raw_and_only_its_images(tmp_path: Path) -> None:
    export = tmp_path / "biol-export"
    export.mkdir()
    _write_export(export)
    qx = enumerate_quizzes(export)
    alpha, beta = qx.exams

    out_a = tmp_path / "out_alpha"
    res_a = convert_qti_exam(alpha, qx, out_a, answer_key=True)
    assert (out_a / "Quiz Alpha.raw.md").exists()
    raw = (out_a / "Quiz Alpha.raw.md").read_text(encoding="utf-8")
    assert raw.startswith("# Quiz Alpha")
    assert "## Question 1" in raw
    assert "Right ✓" in raw
    assert (out_a / "images" / "fig.png").exists()  # Alpha references fig
    assert any(p.name == "fig.png" for p in res_a.images)

    out_b = tmp_path / "out_beta"
    convert_qti_exam(beta, qx, out_b, answer_key=True)
    assert (out_b / "Quiz Beta.raw.md").exists()
    assert not (out_b / "images").exists()  # Beta references no figure


def test_safe_image_name_strips_spaces_and_parens() -> None:
    out = _safe_image_name("Screen Shot 2020-12-06 at 3.41.32 PM (1)-3-1.png")
    assert " " not in out and "(" not in out and ")" not in out
    assert out.endswith(".png")
    assert out == "Screen_Shot_2020-12-06_at_3.41.32_PM_1_-3-1.png"


def test_extract_course_from_manifest_title() -> None:
    xml = (
        '<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">'
        '<metadata><imsmd:lom xmlns:imsmd="x"><imsmd:general><imsmd:title>'
        '<imsmd:string>QTI Quiz Export for course "DEMO-1010-001-Fall 2024"</imsmd:string>'
        "</imsmd:title></imsmd:general></imsmd:lom></metadata><resources/></manifest>"
    )
    assert _extract_course(xml) == "DEMO-1010-001-Fall 2024"


def test_to_markdown_fans_out_one_full_pipeline_doc_per_exam(tmp_path: Path) -> None:
    # End-to-end: one export → one independent full-pipeline document dir per
    # exam (own checkpoints, own images/, own sections/ per-question split).
    from pagespeak import to_markdown

    export = tmp_path / "biol-export"
    export.mkdir()
    _write_export(export)
    out = tmp_path / "out"

    result = to_markdown(export, output_dir=out, diagrams=False)
    assert result.source_format == "qti"

    alpha = out / "Quiz Alpha"
    # full pipeline checkpoints, per exam
    assert (alpha / "Quiz Alpha.raw.md").exists()
    assert (alpha / "Quiz Alpha.cleaned.md").exists()
    assert (alpha / "Quiz Alpha.visioned.md").exists()
    assert (alpha / "Quiz Alpha.md").exists()  # master
    assert (alpha / ".pagespeak-run.json").exists()
    # own images
    assert (alpha / "images" / "fig.png").exists()
    # per-question split with frontmatter
    q1 = (alpha / "sections" / "Question 001.md").read_text(encoding="utf-8")
    assert 'exam: "Quiz Alpha"' in q1
    assert "question_number: 1" in q1
    assert "![a figure](../images/fig.png)" in q1
    # master carries exam-level frontmatter
    master = (alpha / "Quiz Alpha.md").read_text(encoding="utf-8")
    assert master.startswith("---\n")
    assert 'course: "DEMO-1010-001-Fall 2024"' in master
    # second exam is its own independent doc dir
    assert (out / "Quiz Beta" / "Quiz Beta.md").exists()
    assert (out / "Quiz Beta" / "sections" / "Question 001.md").exists()


def test_enumerate_quizzes_rejects_qti_href_traversal(tmp_path: Path) -> None:
    # A malicious manifest whose QTI resource href escapes the export root must
    # be rejected, not read — `root / href` is otherwise an arbitrary file read
    # (the read contents land in the output markdown + the vision payload).
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    export = tmp_path / "export"
    export.mkdir()
    manifest = (
        '<?xml version="1.0"?>'
        '<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">'
        "<resources>"
        '<resource identifier="gAAA" type="imsqti_xmlv1p2">'
        '<file href="../secret.txt"/>'
        "</resource>"
        "</resources></manifest>"
    )
    (export / "imsmanifest.xml").write_text(manifest, encoding="utf-8")
    with pytest.raises(ValueError, match="escape"):
        enumerate_quizzes(export)


def test_enumerate_quizzes_rejects_media_href_traversal(tmp_path: Path) -> None:
    # A webcontent (media) href that escapes the export root must be rejected at
    # enumeration, before the per-exam resolver copies it into images/.
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    export = tmp_path / "export"
    export.mkdir()
    manifest = (
        '<?xml version="1.0"?>'
        '<manifest xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">'
        "<resources>"
        '<resource identifier="figres" type="webcontent" href="../secret.txt">'
        '<file href="../secret.txt"/>'
        "</resource>"
        "</resources></manifest>"
    )
    (export / "imsmanifest.xml").write_text(manifest, encoding="utf-8")
    with pytest.raises(ValueError, match="escape"):
        enumerate_quizzes(export)
