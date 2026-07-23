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
    check_misaligned_table,
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


# ── misaligned_table ───────────────────────────────────────────────────────


# The real defect shape: a wide multi-column spec sheet whose cell boundaries
# drifted during extraction, so two labels land merged in one label-column
# cell and values shift under the wrong label.
_MISALIGNED_SPEC_TABLE = (
    "|  | Crossover Frequency: | 2.6 kHz 4th order LF / 2nd order |\n"
    "| --- | --- | --- |\n"
    "|  | Distortion, 96 dB, 1 m: Mid-High Range (200 Hz - 20 kHz) | HF (model B) |\n"
    "|  | 2nd Harmonic: | <0.4% |\n"
    "|  | 3rd Harmonic: | <0.3% |\n"
    "|  | Input Connector: Noise Level: | IEC <13 dBA / 1 m |\n"
    "|  | Peak Level: | 112 dB / 1 m |\n"
)


def test_misaligned_table_merged_labels_flagged() -> None:
    findings = check_misaligned_table(_MISALIGNED_SPEC_TABLE)
    assert len(findings) == 2
    assert all(f.check == "misaligned_table" for f in findings)
    # warning, not error: the defect is real RAG noise but not auto-fixable
    # (Marker and Docling reproduce it identically) — report-only, like
    # duplicate_heading.
    assert all(f.severity == "warning" for f in findings)
    assert [f.line for f in findings] == [3, 6]


def test_misaligned_table_blank_form_ok() -> None:
    """A blank fill-in form flattened to one column — merged labels but an
    EMPTY value cell. No data landed under the wrong label, so it is not the
    spillover defect (and is faithful to an authored blank form)."""
    text = (
        "|  | Name: Model: |\n"
        "| --- | --- |\n"
        "|  | Company: Serial Number: |\n"
        "|  | Address: Store: |\n"
        "|  | Email: Date: |\n"
    )
    assert check_misaligned_table(text) == []


def test_misaligned_table_worksheet_multi_prompt_cell_ok() -> None:
    """An authored fill-in worksheet: one cell holds a label plus several
    colon-prompts, beside an EMPTY answer cell. The empty column is by
    design — nothing is misattributed."""
    text = (
        "|  |  |\n"
        "| --- | --- |\n"
        "| Strand #1: 3'-TAC-5'  Complementary sequence:  mRNA sequence:  Type: |  |\n"
        "| Strand #2: 3'-TAG-5'  Complementary sequence:  mRNA sequence:  Type: |  |\n"
        "| Strand #3: 3'-TAA-5'  Complementary sequence:  mRNA sequence:  Type: |  |\n"
    )
    assert check_misaligned_table(text) == []


def test_misaligned_table_clean_key_value_ok() -> None:
    """A well-formed 2-column spec table — every label one colon-terminated
    phrase — is the closest legitimate shape and must not be flagged."""
    text = (
        "| Frequency Response: | 50 Hz - 20 kHz |\n"
        "| --- | --- |\n"
        "| Power Rating (rated impedance): | 150 watts |\n"
        "| Impedance: | 8 ohms |\n"
        "| Signal-to-Noise: | 96 dB |\n"
    )
    assert check_misaligned_table(text) == []


def test_misaligned_table_colon_in_value_column_ok() -> None:
    """Colon-space inside a VALUE cell is content (a note, a ratio caption),
    not a merged label — only the label column is scanned."""
    text = (
        "| AC Input: | 115 VAC, 60 Hz (note: EU models differ) |\n"
        "| --- | --- |\n"
        "| Fuse: | 2 A slow-blow |\n"
        "| Power: | 45 W typical |\n"
    )
    assert check_misaligned_table(text) == []


def test_misaligned_table_instruction_table_ok() -> None:
    """A worked-example table (instruction | math) has no colon-terminated
    label column, so interior colons there are never scanned."""
    text = (
        "|  |  |\n"
        "| --- | --- |\n"
        "|  | $3x^{2}+7x-9=0$ |\n"
        "| Identify *a*, *b*, and *c*. | $a=3, b=7, c=-9$ |\n"
        "| Write the discriminant. | $b^{2}-4ac$ |\n"
        "| Simplify. | $157$ |\n"
    )
    assert check_misaligned_table(text) == []


def test_misaligned_table_alignment_colons_ok() -> None:
    """`:---:` alignment syntax in the separator row is not a label."""
    text = "| Name: | Value |\n|:---|---:|\n| Width: | 20 cm |\n| Height: | 30 cm |\n"
    assert check_misaligned_table(text) == []


def test_misaligned_table_time_and_url_colons_ok() -> None:
    """Colons without a following space (times, URLs) are never merged labels."""
    text = (
        "| Start Time: | 10:30 |\n"
        "| --- | --- |\n"
        "| Manual URL: | https://example.com/doc |\n"
        "| Duration: | 45 min |\n"
    )
    assert check_misaligned_table(text) == []


def test_misaligned_table_ignores_fenced_code() -> None:
    text = f"```\n{_MISALIGNED_SPEC_TABLE}```\n"
    assert check_misaligned_table(text) == []


def test_misaligned_table_small_table_ok() -> None:
    """Too few label cells to classify a label column — never flagged."""
    text = "| Note: See manual: page 3 | x |\n| --- | --- |\n| b | y |\n"
    assert check_misaligned_table(text) == []


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


def test_bold_inline_code_is_not_shattered_emphasis() -> None:
    """`**`⌘ + S`**` is legitimate bold-wrapped inline code. Blanking the code
    span to an empty string fused the surrounding markers into `****` and
    flagged clean prose; the span must blank to a spacer instead."""
    text = "Save with **`⌘ + S`** or tick **`Receive Beta Updates`** in settings.\n"
    assert check_shattered_emphasis(text) == []


def test_real_shattered_run_still_flags() -> None:
    text = "The compound ****CO****2**** dissolves readily.\n"
    findings = check_shattered_emphasis(text)
    assert len(findings) == 1 and findings[0].check == "shattered_emphasis"
