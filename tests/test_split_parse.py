"""Tests for pagespeak.services._split_parse."""

from __future__ import annotations

from pagespeak.services._split_parse import _parse_any_heading, _parse_numbered_heading


def test_measurement_heading_is_not_numbered_in_min_level_mode() -> None:
    """`## 6.3 mm stereo jack plug` labels a connector, not section 6.3.

    Default mode rejects these; min-level mode applied neither guard, so a spec
    table leaked `6.3/` folders into the split. The heading is still a section —
    just an unnumbered one.
    """
    assert _parse_any_heading("## 6.3 mm stereo jack plug", min_level=2) == (
        "##",
        None,
        "6.3 mm stereo jack plug",
    )
    assert _parse_any_heading("#### 35 mm and 65 mm", min_level=2) == (
        "####",
        None,
        "35 mm and 65 mm",
    )


def test_measurement_unit_heading_is_not_numbered_in_min_level_mode() -> None:
    """Uppercase-initial units (`48 V`, `2.4 GHz`) need the second guard."""
    assert _parse_any_heading("### 48 V phantom power", min_level=2) == (
        "###",
        None,
        "48 V phantom power",
    )
    assert _parse_any_heading("## 2.4 GHz band", min_level=2) == ("##", None, "2.4 GHz band")


def test_real_numbered_headings_still_parse_in_min_level_mode() -> None:
    """The guard must not swallow genuine numbered sections."""
    assert _parse_any_heading("## 1.4 Configuration", min_level=2) == ("##", "1.4", "Configuration")
    assert _parse_any_heading("# 2. INSTALLATION", min_level=2) == ("#", "2", "INSTALLATION")
    assert _parse_any_heading("### 1.4.1 Wiring", min_level=2) == ("###", "1.4.1", "Wiring")


def test_measurement_guards_agree_across_both_parse_modes() -> None:
    """Default mode already rejected these; the two modes must not disagree."""
    for line in ("## 6.3 mm stereo jack plug", "### 48 V phantom power", "## 2.4 GHz band"):
        assert _parse_numbered_heading(line) is None
        assert (_parse_any_heading(line, min_level=2) or (None, None, None))[1] is None
