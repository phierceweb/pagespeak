"""Tests for services._audit_extraction — backend extraction-damage checks."""

from __future__ import annotations

from pagespeak.services._audit_extraction import (
    check_collapsed_code_blocks,
    check_formula_glyph_codes,
    check_unclosed_code_fence,
)


def _fences(bodies: list[str], lang: str = "") -> str:
    return "\n\n".join(f"```{lang}\n{body}\n```" for body in bodies) + "\n"


def test_every_code_block_one_line_is_flagged() -> None:
    """The collapsed-code signature: a whole document's blocks at one line each."""
    md = "# Guide\n\nRun these.\n\n" + _fences([f"cmd --flag {i} ˓→ more" for i in range(8)])
    findings = check_collapsed_code_blocks(md)
    assert [f.check for f in findings] == ["collapsed_code_blocks"]
    assert "8" in findings[0].message


def test_a_multi_line_block_clears_the_document() -> None:
    blocks = [f"cmd {i}" for i in range(8)] + ["line one\nline two"]
    assert check_collapsed_code_blocks(_fences(blocks)) == []


def test_few_one_line_blocks_are_not_evidence() -> None:
    assert check_collapsed_code_blocks(_fences(["a", "b", "c"])) == []


def test_mermaid_fences_do_not_count() -> None:
    md = _fences([f"x{i}" for i in range(8)], lang="mermaid")
    assert check_collapsed_code_blocks(md) == []


def test_formula_glyph_codes_are_flagged() -> None:
    prose = "The rate is given by n01 n28 n2a over n14, and n0c n33 bounds it. " * 4
    findings = check_formula_glyph_codes("# Kinetics\n\n" + prose)
    assert [f.check for f in findings] == ["formula_glyph_codes"]


def test_clean_prose_and_code_are_not_glyph_codes() -> None:
    prose = "Connect the n-type layer. The nab and nee words stay clean. " * 20
    code = "```\nn01 n02 n03 n04 n05 n06\n```\n"
    assert check_formula_glyph_codes(prose + "\n\n" + code) == []


def test_an_unclosed_fence_is_flagged_with_how_much_it_swallows() -> None:
    """Every later line renders as code and every fence-aware pass skips it."""
    md = "# Guide\n\n```\nconfig line\n\n## Next Section\n\nprose\n"
    findings = check_unclosed_code_fence(md)
    assert [f.check for f in findings] == ["unclosed_code_fence"]
    assert findings[0].line == 3
    assert "5 line" in findings[0].message


def test_closed_fences_are_fine() -> None:
    assert check_unclosed_code_fence("```\na\n```\n\n~~~\nb\n~~~\n") == []
