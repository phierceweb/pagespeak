"""Tests for `split_into_sections(authored_levels=True)`: nest by heading level,
keep a leading number as title text."""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.services._split import split_into_sections
from pagespeak.services._split_parse import _detect_fallback_min_level
from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_split import check_split


def _doc(*headings: str) -> str:
    """Each heading followed by a one-line body named after it."""
    return "".join(f"{h}\n\n{h.lstrip('# ')} body.\n\n" for h in headings)


WIDGET_DOC = _doc(
    "# Widget Guide",
    "## Set up widgets",
    "### Widget formats",
    "#### Quad widget format",
    "#### 5.1 (Type A) widget format",
    "#### 5.1.2 widget format",
    "#### 7.1 widget format",
    "### Place widgets",
)

F = Path("widget-guide/set-up-widgets/widget-formats")


def _split(tmp_path: Path, markdown: str = WIDGET_DOC, **kwargs: object) -> Path:
    out = tmp_path / "sections"
    options: dict[str, object] = {
        "nested": True,
        "min_level": 1,
        "min_body_chars": 1,
        "doc_title": "Widget Guide",
        "authored_levels": True,
    }
    options.update(kwargs)
    split_into_sections(markdown, out, **options)  # type: ignore[arg-type]
    return out


def _paths(out: Path) -> list[str]:
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md") if p.name != "INDEX.md")


def _frontmatter(path: Path) -> dict[str, object]:
    head = path.read_text(encoding="utf-8").split("---\n")[1]
    pairs = (line.split(": ", 1) for line in head.splitlines())
    return {key: json.loads(value) for key, value in pairs}


def _heading(path: Path) -> str:
    return next(ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("#"))


def test_numbered_titles_nest_under_their_level_parent(tmp_path: Path) -> None:
    out = _split(tmp_path)
    for name in ("5-1-type-a-widget-format.md", "5-1-2-widget-format.md", "7-1-widget-format.md"):
        assert (out / F / name).is_file(), name
    assert not (out / "5").exists()
    assert not (out / "7").exists()


def test_index_lists_only_level_roots(tmp_path: Path) -> None:
    out = _split(tmp_path)
    entries = [ln for ln in (out / "INDEX.md").read_text().splitlines() if ln.startswith("- [")]
    assert entries == ["- [Widget Guide](widget-guide/widget-guide.md)"]


def test_heading_and_frontmatter_keep_number_verbatim(tmp_path: Path) -> None:
    path = _split(tmp_path) / F / "5-1-type-a-widget-format.md"
    assert _heading(path) == "#### 5.1 (Type A) widget format"
    fm = _frontmatter(path)
    assert fm["section_title"] == "5.1 (Type A) widget format"
    assert "section_number" not in fm
    assert fm["section_path"] == ["Widget Guide", "Set up widgets", "Widget formats"]
    assert fm["depth"] == 3
    assert fm["parent_id"] == "widget-guide/set-up-widgets/widget-formats.md"


def test_breadcrumb_and_subsections_follow_levels(tmp_path: Path) -> None:
    out = _split(tmp_path)
    text = (out / F / "5-1-type-a-widget-format.md").read_text()
    crumb = next(ln for ln in text.splitlines() if ln.startswith("> ↑"))
    assert crumb.endswith("/ [Widget formats](../widget-formats.md)")
    parent = (out / F.parent / "widget-formats.md").read_text()
    subsections = parent.split("## Subsections", 1)[1]
    listed = [ln for ln in subsections.splitlines() if ln.startswith("- [")]
    assert listed == [
        "- [Quad widget format](widget-formats/quad-widget-format.md)",
        "- [5.1 (Type A) widget format](widget-formats/5-1-type-a-widget-format.md)",
        "- [5.1.2 widget format](widget-formats/5-1-2-widget-format.md)",
        "- [7.1 widget format](widget-formats/7-1-widget-format.md)",
    ]


def test_chapter_heading_kept_and_link_resolves(tmp_path: Path) -> None:
    markdown = (
        "# Gear Book\n\nBook body.\n\n"
        "## Chapter 2 Gears\n\nGears body.\n\n"
        "## 2.1 Teeth\n\n[see](#chapter-2-gears)\n"
    )
    out = _split(tmp_path, markdown, doc_title="Gear Book")
    chapter = out / "gear-book" / "chapter-2-gears.md"
    assert _heading(chapter) == "## Chapter 2 Gears"
    teeth = out / "gear-book" / "2-1-teeth.md"
    assert teeth.is_file()
    assert not (out / "gear-book" / "chapter-2-gears").exists()
    assert "[see](chapter-2-gears.md)" in teeth.read_text()


def test_measurement_and_bare_integer_titles_stay_verbatim(tmp_path: Path) -> None:
    markdown = _doc(
        "# Power Guide",
        "## 404 Handling",
        "#### 1. First step",
        "## 48 V Supply",
    )
    out = _split(tmp_path, markdown, doc_title="Power Guide")
    expected = {
        "power-guide/404-handling.md": "## 404 Handling",
        "power-guide/404-handling/1-first-step.md": "#### 1. First step",
        "power-guide/48-v-supply.md": "## 48 V Supply",
    }
    for rel, heading in expected.items():
        assert _heading(out / rel) == heading


def test_numbered_step_after_callout_nests_under_callout(tmp_path: Path) -> None:
    markdown = _doc("# Mixer Guide", "## Route signals", "### Note", "#### 2. Second step")
    out = _split(tmp_path, markdown, doc_title="Mixer Guide")
    step = out / "mixer-guide/route-signals/note/2-second-step.md"
    assert _heading(step) == "#### 2. Second step"


def test_empty_toc_entry_still_dropped(tmp_path: Path) -> None:
    markdown = "# Tooth Book\n\nBook body.\n\n## 1.1 Teeth 32\n\n## 1.1 Teeth\n\nTeeth body.\n"
    out = _split(tmp_path, markdown, doc_title="Tooth Book", min_body_chars=0)
    teeth = [p for p in out.rglob("1-1-teeth*.md")]
    assert len(teeth) == 1
    assert "Teeth body." in teeth[0].read_text()


def test_same_title_sections_resolve_without_overwrite(tmp_path: Path) -> None:
    markdown = (
        "# Book\n\nBook body.\n\n"
        "## 1.1 Ratios\n\nRatios body.\n\n### Learning goals\n\nGoals A.\n\n"
        "## 1.2 Rates\n\nRates body.\n\n### Learning goals\n\nGoals B.\n\n"
        "## Glossary\n\nGloss A.\n\n"
        "## Glossary\n\nGloss B.\n"
    )
    out = _split(tmp_path, markdown, doc_title="Book")
    assert "Goals A." in (out / "book/1-1-ratios/learning-goals.md").read_text()
    assert "Goals B." in (out / "book/1-2-rates/learning-goals.md").read_text()
    assert "Gloss A." in (out / "book/glossary.md").read_text()
    assert "Gloss B." in (out / "book/glossary-2.md").read_text()


def test_flat_split_keeps_number_slugs(tmp_path: Path) -> None:
    out = _split(tmp_path, nested=False)
    path = out / "5-1-type-a-widget-format.md"
    assert path.is_file()
    assert _heading(path) == "#### 5.1 (Type A) widget format"


def test_min_level_none_falls_back_to_detected_level(tmp_path: Path) -> None:
    detected = _detect_fallback_min_level(WIDGET_DOC.splitlines())
    assert detected is not None
    fallback = _split(tmp_path / "a", min_level=None)
    explicit = _split(tmp_path / "b", min_level=detected)
    assert _paths(fallback) == _paths(explicit)
    assert (fallback / F / "5-1-type-a-widget-format.md").is_file()


def test_min_level_none_numbered_doc_gets_no_number_folders(tmp_path: Path) -> None:
    markdown = _doc("# 1 Intro", "## 1.1 Scope", "# 2 Setup", "## 2.1 Power")
    out = _split(tmp_path, markdown, min_level=None)
    assert _paths(out) == [
        "1-intro/1-1-scope.md",
        "1-intro/1-intro.md",
        "2-setup/2-1-power.md",
        "2-setup/2-setup.md",
    ]
    scope = out / "1-intro/1-1-scope.md"
    assert _heading(scope) == "## 1.1 Scope"
    assert "section_number" not in _frontmatter(scope)


def test_split_conserves_master(tmp_path: Path) -> None:
    master = tmp_path / "doc.md"
    master.write_text(WIDGET_DOC, encoding="utf-8")
    split_into_sections(
        WIDGET_DOC,
        tmp_path / "sections",
        nested=True,
        min_level=1,
        min_body_chars=1,
        doc_title="Widget Guide",
        authored_levels=True,
    )
    result = check_split(VerifyDoc(root=tmp_path, master=master))
    assert list(result.findings) == []


def test_default_keeps_number_nesting(tmp_path: Path) -> None:
    out = tmp_path / "sections"
    split_into_sections(WIDGET_DOC, out, nested=True, min_level=1, min_body_chars=1)
    path = out / "5" / "5-1-type-a-widget-format.md"
    assert path.is_file()
    assert _heading(path) == "#### 5.1. (Type A) widget format"
