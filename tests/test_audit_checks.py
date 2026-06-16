"""Tests for services/_audit_checks.py — pure text-defect detectors.

Each positive fixture models a real conversion defect class: a
wide-spec-table collapse, stray `e<5v< td="">` HTML fragments, `[�]`
encoding artifacts, undecoded entities, duplicate junk headings, DOCX
emphasis shatter.
"""

from __future__ import annotations

from pagespeak.services._audit_checks import (
    AuditFinding,
    check_collapsed_table,
    check_duplicate_heading,
    check_html_entity,
    check_html_fragment,
    check_replacement_char,
    check_shattered_emphasis,
    run_text_checks,
)

# ── collapsed_table ────────────────────────────────────────────────────────


def test_collapsed_table_br_blob_flagged() -> None:
    """The collapsed-sheet shape: an entire spec sheet (35+ lines) joined by <br> in ONE cell."""
    cell = "<br>".join(f"Spec {i}: value" for i in range(35))
    text = f"| Specifications |\n|---|\n| {cell} |\n"
    findings = check_collapsed_table(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.check == "collapsed_table"
    assert f.severity == "error"
    assert f.line == 3


def test_collapsed_table_few_br_ok() -> None:
    """A couple of <br> line breaks inside a cell is normal table markdown."""
    text = "| Notes |\n|---|\n| line one<br>line two<br>line three |\n"
    assert check_collapsed_table(text) == []


def test_collapsed_table_legit_multiline_list_cell_ok() -> None:
    """A real multi-line list inside a cell of a populated multi-column table
    (an authored-flat doc shape) must NOT be flagged — a handful of <br>, real columns."""
    cell = "ˆ structure: multiple layers<br>ˆ basement membrane<br>ˆ apical surface"
    text = (
        "| Name | Body locations | Reference |\n"
        "| --- | --- | --- |\n"
        f"| keratinized stratified | {cell} | TABLE 4.3A |\n"
        "| function | protection of tissue | TABLE 4.3B |\n"
    )
    assert check_collapsed_table(text) == []


def test_collapsed_table_moderate_spec_cell_ok() -> None:
    """A vertical spec list (a dozen-ish <br>, below the collapse threshold) in
    a real 2-column spec table is legitimate, not a collapse."""
    cell = "<br>".join(
        ["44.1", "kHz,", "48", "kHz,", "88.2", "kHz,", "96", "kHz", "176.4", "kHz", "192", "kHz"]
    )
    text = f"| Supported rates | {cell} |\n| --- | --- |\n| Range | 20 Hz - 20 kHz |\n"
    assert check_collapsed_table(text) == []


def test_collapsed_table_authored_blank_worksheet_ok() -> None:
    """An authored sparse table — short content cells (no <br> jam) interspersed
    with blank rows — is NOT a collapse. A fill-in worksheet shape: label cells
    plus deliberately blank rows. An empty-row run on its own (no mega-cell)
    must NOT be flagged."""
    empty_rows = "\n".join("|  |  |" for _ in range(10))
    text = (
        "| left atrium |  |\n| --- | --- |\n"
        f"{empty_rows}\n| ascending aorta |  |\n{empty_rows}\n| right atrium |  |\n"
    )
    assert check_collapsed_table(text) == []


def test_collapsed_table_ignores_fenced_code() -> None:
    cell = "<br>".join(str(i) for i in range(35))
    text = f"```\n| {cell} |\n```\n"
    assert check_collapsed_table(text) == []


# ── html_fragment ──────────────────────────────────────────────────────────


def test_html_fragment_table_debris_shape_flagged() -> None:
    """A voltage-table debris shape: a stray `td` fragment left mid-sentence."""
    text = 'Measure between pins: e<5v< td=""> then reconnect.\n'
    findings = check_html_fragment(text)
    assert findings
    assert findings[0].check == "html_fragment"
    assert findings[0].severity == "error"
    assert findings[0].line == 1


def test_html_fragment_stray_table_tags_flagged() -> None:
    text = "Voltage</td> reading <tr> here\n"
    assert check_html_fragment(text)


def test_html_fragment_whitelists_legit_inline_html() -> None:
    """<br> and page-anchor spans are pagespeak's own legitimate output."""
    text = 'a<br>b\n<span id="page-3-0"></span>\n'
    assert check_html_fragment(text) == []


def test_html_fragment_angle_wrapped_link_targets_ok() -> None:
    """angle-wraps link targets with spaces — `(<Table of
    Contents.md>)` is a markdown link, not HTML debris (the INDEX.md shape)."""
    text = (
        "- [Table of Contents](<Table of Contents/Table of Contents.md>)\n"
        "- [Troubleshooting](<tr area/Troubleshooting.md>)\n"
    )
    assert check_html_fragment(text) == []


def test_html_fragment_ignores_fenced_code() -> None:
    text = "```html\n<td>real example</td>\n```\n"
    assert check_html_fragment(text) == []


def test_html_fragment_ignores_inline_code_tag() -> None:
    """A tag documented in inline code (an HTML manual) is content, not debris."""
    assert check_html_fragment("Use `<td>` and `</td>` to build a table cell.") == []


def test_html_entity_ignores_inline_code_entity() -> None:
    """An entity shown in inline code is documentation, not an undecoded entity."""
    assert check_html_entity("Escape a less-than sign as `&amp;lt;` in the source.") == []


# ── replacement_char ───────────────────────────────────────────────────────


def test_replacement_char_flagged() -> None:
    """The encoding-damage shape: [�] where Ω should be."""
    text = "Resistance: 5 [�] nominal\n"
    findings = check_replacement_char(text)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "1 occurrence" in findings[0].message


def test_replacement_char_counts_all() -> None:
    text = "� one\nand � two �\n"
    findings = check_replacement_char(text)
    assert len(findings) == 1
    assert "3 occurrence" in findings[0].message


def test_replacement_char_clean_ok() -> None:
    assert check_replacement_char("Resistance: 5 Ω nominal\n") == []


# ── html_entity ────────────────────────────────────────────────────────────


def test_html_entity_named_flagged() -> None:
    """Undecoded named entities cleanup should have decoded — audit catches regressions."""
    text = "T3 &lt; 34F and A &amp; B\n"
    findings = check_html_entity(text)
    assert findings
    assert findings[0].check == "html_entity"


def test_html_entity_numeric_flagged() -> None:
    assert check_html_entity("it&#8217;s here\n")
    assert check_html_entity("space&#x20;here\n")


def test_html_entity_plain_ampersand_ok() -> None:
    assert check_html_entity("Acme & Sons, R&D dept\n") == []


def test_html_entity_unknown_word_ok() -> None:
    """`&foo;` shaped prose isn't on the curated entity list — don't flag."""
    assert check_html_entity("see &weirdword; usage\n") == []


def test_html_entity_ignores_fenced_code() -> None:
    text = "```\ncode = a &lt; b\n```\n"
    assert check_html_entity(text) == []


# ── shattered_emphasis ─────────────────────────────────────────────────────


def test_shattered_emphasis_flagged() -> None:
    """The DOCX run-shatter shape: **CO****2** style marker pileups."""
    findings = check_shattered_emphasis("the **CO****2** transport\n")
    assert findings
    assert findings[0].severity == "error"


def test_shattered_emphasis_bold_italic_ok() -> None:
    assert check_shattered_emphasis("***really*** important\n") == []


def test_shattered_emphasis_hr_line_ok() -> None:
    """A line of only asterisks is a markdown horizontal rule, not shatter."""
    assert check_shattered_emphasis("above\n\n****\n\nbelow\n") == []


def test_shattered_emphasis_ignores_fenced_code() -> None:
    assert check_shattered_emphasis("```\nx = a ****b\n```\n") == []


# ── duplicate_heading ──────────────────────────────────────────────────────


def _heading_doc(title: str, times: int) -> str:
    parts = []
    for i in range(times):
        parts.append(f"## {title}\n\nbody {i}\n")
    return "\n".join(parts)


def test_duplicate_heading_numbered_procedure_shape_flagged() -> None:
    """`Important note:` ×12 — a numbered-procedure manual junk-heading defect (report-only)."""
    findings = check_duplicate_heading(_heading_doc("Important note:", 12))
    assert len(findings) == 1
    f = findings[0]
    assert f.check == "duplicate_heading"
    assert f.severity == "warning"
    assert "12" in f.message and "Important note:" in f.message


def test_duplicate_heading_below_threshold_ok() -> None:
    assert check_duplicate_heading(_heading_doc("Overview", 3)) == []


def test_duplicate_heading_case_insensitive() -> None:
    text = "## Setup\n\na\n\n## SETUP\n\nb\n\n## setup\n\nc\n\n## Setup\n\nd\n"
    assert check_duplicate_heading(text)


def test_duplicate_heading_subsections_excluded() -> None:
    """`## Subsections` is splitter furniture, present in many files."""
    assert check_duplicate_heading(_heading_doc("Subsections", 9)) == []


# ── run_text_checks + general robustness ───────────────────────────────────


def test_run_text_checks_aggregates_all() -> None:
    text = "T3 &lt; 34F\nand � too\n"
    checks = {f.check for f in run_text_checks(text)}
    assert checks == {"html_entity", "replacement_char"}


def test_run_text_checks_empty_input() -> None:
    assert run_text_checks("") == []


def test_run_text_checks_unicode_safe() -> None:
    text = "## Überschrift 🎛️\n\nGain ±3 dB, ΔE < 2, 試験\n"
    assert run_text_checks(text) == []


def test_finding_is_frozen() -> None:
    f = AuditFinding(check="x", severity="error", line=1, message="m")
    try:
        f.line = 2  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("AuditFinding must be frozen")
