"""Tests for services/_audit.py — file-context checks, tree walk, report."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._audit import (
    audit_file,
    audit_paths,
    check_dangling_image_refs,
    check_empty_section,
    render_report,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_dangling_image_ref_resolves_percent_encoded(tmp_path: Path) -> None:
    """A `%`-encoded local target must resolve to its decoded file on disk,
    not be reported as dangling (a writer may emit `%20` for a spaced name)."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "My Fig.png").write_bytes(b"x")
    md = _write(tmp_path / "doc.md", "![f](images/My%20Fig.png)\n")
    assert check_dangling_image_refs(md) == []


_NAV_NODE_SECTION = (
    "---\n"
    'section_title: "Preface"\n'
    "heading_level: 2\n"
    "---\n"
    "# 1. Preface\n"
    '<span id="page-3-0"></span>\n'
    "\n"
    "> ↑ [Manual](../INDEX.md) / [Part I](<1. Part I.md>)\n"
    "\n"
    "## Subsections\n"
    "\n"
    "- [Export Notes](<Export Notes.md>)\n"
    "- [Legal](<Legal.md>)\n"
)

_ORPHAN_SHELL_SECTION = (
    "---\n"
    'section_title: "Preface"\n'
    "heading_level: 2\n"
    "---\n"
    "# 1. Preface\n"
    '<span id="page-3-0"></span>\n'
    "\n"
    "> ↑ [Manual](../INDEX.md) / [Part I](<1. Part I.md>)\n"
)


# ── empty_section ──────────────────────────────────────────────────────────


def test_empty_section_orphan_shell_flagged(tmp_path: Path) -> None:
    """No body AND no subsections — a true shell the splitter should drop."""
    f = _write(tmp_path / "doc" / "sections" / "1" / "1. Preface.md", _ORPHAN_SHELL_SECTION)
    findings = check_empty_section(f)
    assert len(findings) == 1
    assert findings[0].check == "empty_section"
    assert findings[0].severity == "warning"


def test_empty_section_nav_node_ok(tmp_path: Path) -> None:
    """A parent with a Subsections list is a deliberate nav node (a long-titled
    reference doc shape) — its content legitimately lives in its children."""
    f = _write(tmp_path / "doc" / "sections" / "1" / "1. Preface.md", _NAV_NODE_SECTION)
    assert check_empty_section(f) == []


def test_empty_section_with_body_ok(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "doc" / "sections" / "1. Preface.md",
        _ORPHAN_SHELL_SECTION + "\nActual prose the reader came for.\n",
    )
    assert check_empty_section(f) == []


def test_empty_section_only_applies_under_sections(tmp_path: Path) -> None:
    """A short master/INDEX file is not a 'section shell'."""
    f = _write(tmp_path / "doc" / "INDEX.md", "# Split Sections: x\n")
    assert check_empty_section(f) == []


# ── dangling_image_ref ─────────────────────────────────────────────────────


def test_dangling_image_ref_flagged(tmp_path: Path) -> None:
    f = _write(tmp_path / "doc" / "doc.md", "![caption](images/missing.png)\n")
    findings = check_dangling_image_refs(f)
    assert len(findings) == 1
    assert findings[0].check == "dangling_image_ref"
    assert "missing.png" in findings[0].message


def test_dangling_image_ref_existing_ok(tmp_path: Path) -> None:
    _write(tmp_path / "doc" / "images" / "fig.png", "x")
    f = _write(tmp_path / "doc" / "doc.md", "![caption](images/fig.png)\n")
    assert check_dangling_image_refs(f) == []


def test_dangling_image_ref_skips_external_urls(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "doc.md",
        "![a](https://example.com/x.png)\n![b](data:image/png;base64,xx)\n",
    )
    assert check_dangling_image_refs(f) == []


def test_dangling_image_ref_angle_wrapped_target(tmp_path: Path) -> None:
    """Writes space-containing targets angle-wrapped — resolve those."""
    _write(tmp_path / "images" / "my fig.png", "x")
    f = _write(tmp_path / "doc.md", "![a](<images/my fig.png>)\n")
    assert check_dangling_image_refs(f) == []


# ── audit_file / audit_paths walk ──────────────────────────────────────────


def test_audit_file_combines_text_and_context_checks(tmp_path: Path) -> None:
    f = _write(tmp_path / "doc.md", "T3 &lt; 34F\n![x](images/gone.png)\n")
    checks = {fi.check for fi in audit_file(f)}
    assert checks == {"html_entity", "dangling_image_ref"}


def test_audit_paths_skips_checkpoints_and_dot_dirs(tmp_path: Path) -> None:
    root = tmp_path / "out" / "manual"
    _write(root / "manual.md", "clean body\n")
    _write(root / "manual.raw.md", "T3 &lt; 34F\n")  # checkpoint: skip
    _write(root / "manual.cleaned.md", "&amp;\n")  # checkpoint: skip
    _write(root / ".vision-cache" / "x.md", "&amp;\n")  # dot-dir: skip
    _write(root / "chunks" / "0-49" / "raw.md", "&amp;\n")  # ingest intermediate: skip
    report = audit_paths([tmp_path / "out"])
    assert report.files_scanned == 1
    assert report.error_count == 0


def test_audit_paths_accepts_single_file(tmp_path: Path) -> None:
    f = _write(tmp_path / "one.md", "has � char\n")
    report = audit_paths([f])
    assert report.files_scanned == 1
    assert report.error_count == 1


def test_audit_paths_counts_by_check(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x &lt; y\n")
    _write(tmp_path / "b.md", "p &gt; q\nand �\n")
    report = audit_paths([tmp_path])
    assert report.counts_by_check["html_entity"] == 2
    assert report.counts_by_check["replacement_char"] == 1
    assert report.error_count == 3
    assert report.warning_count == 0


def test_audit_paths_warnings_separate_from_errors(tmp_path: Path) -> None:
    body = "\n".join(f"## Important note:\n\nbody {i}\n" for i in range(5))
    _write(tmp_path / "doc.md", body)
    report = audit_paths([tmp_path])
    assert report.error_count == 0
    assert report.warning_count == 1


# ── render_report ──────────────────────────────────────────────────────────


def test_render_report_clean(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "all good\n")
    out = render_report(audit_paths([tmp_path]))
    assert "0 errors" in out
    assert "1 file" in out


def test_render_report_names_file_line_and_check(tmp_path: Path) -> None:
    f = _write(tmp_path / "bad.md", "ok line\nT3 &lt; 34F\n")
    out = render_report(audit_paths([f]))
    assert "bad.md" in out
    assert "html_entity" in out
    assert ":2" in out


def test_render_report_caps_repeats_per_check(tmp_path: Path) -> None:
    """A 50-entity file must not produce 50 report lines."""
    _write(tmp_path / "noisy.md", "\n".join("x &lt; y" for _ in range(50)) + "\n")
    out = render_report(audit_paths([tmp_path]))
    assert "and 47 more" in out


def test_render_report_summary_only(tmp_path: Path) -> None:
    f = _write(tmp_path / "bad.md", "T3 &lt; 34F\n")
    out = render_report(audit_paths([f]), summary_only=True)
    assert "html_entity" in out
    assert ":1" not in out
