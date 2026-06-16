"""Canvas QTI XML → normalized quiz model.

Parses the two XML files Canvas emits per quiz:

- `assessment_meta.xml` (Canvas `cccv1p0`) → title, points, instructions.
- `<hash>.xml` (IMS QTI 1.2 `questestinterop`) → the questions.

Namespace handling uses the `{*}` ElementPath wildcard so the parser is
not pinned to an exact QTI namespace URI. (Note: `Element.iter()` does
NOT support that wildcard — only `find`/`findall` do — so all element
lookups here go through `findall`/`find`.)

Correct answers are read from each item's `<resprocessing>`: every
`<varequal>` that is not wrapped in a `<not>` is a correct selection. Each
question type interprets those `(respident, value)` pairs differently
(see `_parse_item`).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.parse import unquote

from pf_core.log import get_logger

from ..models._quiz import Quiz, QuizOption, QuizQuestion
from ..utils._html import html_fragment_to_markdown

logger = get_logger(__name__)

_IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
_CHOICE_TYPES = frozenset(
    {"multiple_choice_question", "true_false_question", "multiple_answers_question"}
)

_Resolver = Callable[[str], str] | None


def _ln(tag: str) -> str:
    """Local name of a possibly-namespaced tag (`{ns}foo` -> `foo`)."""
    return tag.rsplit("}", 1)[-1]


def _meta_field(item: ET.Element, label: str) -> str | None:
    """Read a `<qtimetadatafield>` value by its `<fieldlabel>`."""
    for field in item.findall(".//{*}qtimetadatafield"):
        fl = field.find("{*}fieldlabel")
        if fl is not None and (fl.text or "").strip() == label:
            fe = field.find("{*}fieldentry")
            return (fe.text or "").strip() if fe is not None else None
    return None


def _clean(el: ET.Element | None, media_resolver: _Resolver = None) -> str:
    """Clean a `<mattext>` element's (HTML) content into markdown."""
    if el is None:
        return ""
    return html_fragment_to_markdown(el.text or "", media_resolver=media_resolver)


def _choice_labels(rl: ET.Element) -> list[ET.Element]:
    rc = rl.find("{*}render_choice")
    return rc.findall("{*}response_label") if rc is not None else []


def _collect_varequal(el: ET.Element, out: list[tuple[str | None, str]]) -> None:
    """Collect `(respident, value)` from every `<varequal>` that is NOT
    inside a `<not>` (those mark INcorrect selections in multiple-answers)."""
    for child in el:
        ln = _ln(child.tag)
        if ln == "not":
            continue
        if ln == "varequal":
            out.append((child.get("respident"), (child.text or "").strip()))
        else:
            _collect_varequal(child, out)


def _correct_pairs(resproc: ET.Element | None) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    if resproc is not None:
        _collect_varequal(resproc, out)
    return out


def _image_basenames(raw_html: str) -> list[str]:
    """Media-image basenames referenced by a stem (skips equation images)."""
    names: list[str] = []
    for src in _IMG_SRC_RE.findall(raw_html or ""):
        if "equation_images" in src:
            continue
        name = unquote(src).split("/")[-1]
        if name:
            names.append(name)
    return names


def _options(rl: ET.Element, correct_ids: set[str], media_resolver: _Resolver) -> list[QuizOption]:
    opts: list[QuizOption] = []
    for label in _choice_labels(rl):
        ident = label.get("ident", "")
        opts.append(
            QuizOption(
                text_md=_clean(label.find("{*}material/{*}mattext"), media_resolver),
                is_correct=ident in correct_ids,
                ident=ident,
            )
        )
    return opts


def _parse_item(item: ET.Element, number: int, media_resolver: _Resolver) -> QuizQuestion:
    qtype = _meta_field(item, "question_type") or "unknown"
    try:
        points = float(_meta_field(item, "points_possible") or 0.0)
    except ValueError:
        logger.warning(
            "qti_non_numeric_points question=%d value=%r",
            number,
            _meta_field(item, "points_possible"),
        )
        points = 0.0

    pres = item.find("{*}presentation")
    stem_el = pres.find("{*}material/{*}mattext") if pres is not None else None
    raw_stem = stem_el.text if stem_el is not None else ""
    stem_md = html_fragment_to_markdown(raw_stem or "", media_resolver=media_resolver)
    image_refs = _image_basenames(raw_stem or "")

    pairs = _correct_pairs(item.find("{*}resprocessing"))
    response_lids = pres.findall("{*}response_lid") if pres is not None else []

    options: list[QuizOption] = []
    matches: list[tuple[str, str]] = []
    blanks: dict[str, list[str]] = {}
    accepted: list[str] = []

    if qtype in _CHOICE_TYPES:
        correct_ids = {v for (ri, v) in pairs if ri == "response1"}
        if response_lids:
            options = _options(response_lids[0], correct_ids, media_resolver)
    elif qtype == "matching_question":
        correct_by_resp = {ri: v for (ri, v) in pairs}
        for rl in response_lids:
            resp = rl.get("ident", "")
            left = _clean(rl.find("{*}material/{*}mattext"), media_resolver)
            match_id = correct_by_resp.get(resp)
            right = ""
            for label in _choice_labels(rl):
                if label.get("ident") == match_id:
                    right = _clean(label.find("{*}material/{*}mattext"), media_resolver)
                    break
            matches.append((left, right))
    elif qtype == "fill_in_multiple_blanks_question":
        for rl in response_lids:
            resp = rl.get("ident", "")
            blank_name = _clean(rl.find("{*}material/{*}mattext"), media_resolver) or resp
            correct_ids = {v for (ri, v) in pairs if ri == resp}
            blanks[blank_name] = [
                _clean(label.find("{*}material/{*}mattext"), media_resolver)
                for label in _choice_labels(rl)
                if label.get("ident") in correct_ids
            ]
    elif qtype == "short_answer_question":
        accepted = [v for (ri, v) in pairs if ri == "response1"]
    elif qtype == "essay_question":
        pass  # prompt only — manually graded
    else:
        # Forward-compatible fallback (New Quizzes / numerical / dropdowns):
        # keep the stem and any choices, never crash.
        if response_lids:
            correct_ids = {v for (ri, v) in pairs if ri == "response1"}
            options = _options(response_lids[0], correct_ids, media_resolver)
        logger.warning("qti_unknown_question_type type=%s number=%d", qtype, number)

    return QuizQuestion(
        number=number,
        qtype=qtype,
        points=points,
        stem_md=stem_md,
        options=options,
        matches=matches,
        blanks=blanks,
        accepted=accepted,
        image_refs=image_refs,
    )


def parse_quiz_items(xml_text: str, *, media_resolver: _Resolver = None) -> list[QuizQuestion]:
    """Parse a QTI `questestinterop` document into normalized questions."""
    root = ET.fromstring(xml_text)
    items = root.findall(".//{*}item")
    return [_parse_item(item, i + 1, media_resolver) for i, item in enumerate(items)]


def parse_assessment_meta(xml_text: str) -> tuple[str, float, str]:
    """Parse `assessment_meta.xml` → `(title, points_possible, instructions_md)`."""
    root = ET.fromstring(xml_text)
    title_el = root.find("{*}title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    pts_el = root.find("{*}points_possible")
    try:
        points = float((pts_el.text or "0").strip()) if pts_el is not None else 0.0
    except (ValueError, AttributeError):
        logger.warning(
            "qti_non_numeric_points_possible value=%r",
            pts_el.text if pts_el is not None else None,
        )
        points = 0.0
    desc_el = root.find("{*}description")
    instructions = html_fragment_to_markdown(desc_el.text or "") if desc_el is not None else ""
    return title, points, instructions


def parse_quiz(qti_xml: str, meta_xml: str, *, media_resolver: _Resolver = None) -> Quiz:
    """Parse a quiz's two XML files into a single `Quiz`."""
    title, points, instructions = parse_assessment_meta(meta_xml)
    questions = parse_quiz_items(qti_xml, media_resolver=media_resolver)
    return Quiz(
        title=title,
        points_possible=points,
        instructions_md=instructions,
        questions=questions,
    )
