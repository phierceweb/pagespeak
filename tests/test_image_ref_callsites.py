"""Every module that scans image refs must use the shared parser."""

from __future__ import annotations

from pathlib import Path

from pagespeak.backends._local_images import localize_local_images_in_markdown
from pagespeak.services._audit import check_dangling_image_refs
from pagespeak.services._decorations import _strip_decoration_refs
from pagespeak.services._image_refs import degrade_missing_image_refs

BRACKET_ALT = "A diagram labeled, [a], and, [b], of a manometer"


def _write(base: Path, rel: str) -> Path:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_audit_flags_missing_ref_whose_alt_has_brackets(tmp_path: Path) -> None:
    """The false negative: a dead link the audit reports as clean."""
    doc = tmp_path / "doc.md"
    doc.write_text(f"![{BRACKET_ALT}](images/gone.webp)\n", encoding="utf-8")
    findings = check_dangling_image_refs(doc)
    assert len(findings) == 1
    assert "images/gone.webp" in findings[0].message


def test_audit_does_not_flag_present_ref_carrying_a_title(tmp_path: Path) -> None:
    """The false positive: an invented defect in a healthy document."""
    _write(tmp_path, "images/widget_alpha.jpg")
    doc = tmp_path / "doc.md"
    doc.write_text(
        '![Widget alpha](images/widget_alpha.jpg "Widget alpha detail")\n', encoding="utf-8"
    )
    assert check_dangling_image_refs(doc) == []


def test_local_copy_reaches_image_whose_alt_has_brackets(tmp_path: Path) -> None:
    """The copy gap: a source image the copy pass never fetches."""
    src_root = tmp_path / "src"
    _write(src_root, "images/fig.webp")
    source_path = src_root / "doc.html"
    source_path.write_text("<html></html>", encoding="utf-8")
    output_dir = tmp_path / "out"
    markdown = f"![{BRACKET_ALT}](images/fig.webp)\n"
    _rewritten, copied = localize_local_images_in_markdown(
        markdown, output_dir, source_path=source_path
    )
    assert len(copied) == 1
    assert copied[0].exists()


def test_degrade_reaches_missing_ref_whose_alt_has_brackets(tmp_path: Path) -> None:
    text = f"![{BRACKET_ALT}](images/gone.webp)\n"
    out, n = degrade_missing_image_refs(text, base_dir=tmp_path)
    assert n == 1
    assert "![" not in out
    assert BRACKET_ALT in out


def test_decoration_strip_removes_ref_whose_alt_has_brackets() -> None:
    markdown = f"lead\n\n![{BRACKET_ALT}](images/logo.webp)\n\ntail"
    out = _strip_decoration_refs(markdown, {"logo.webp"}, {"logo.webp"})
    assert "![" not in out
    assert "lead" in out and "tail" in out


def test_decoration_strip_keeps_a_titled_ref_it_was_not_asked_to_remove() -> None:
    markdown = '![alt](images/keep.png "A title")'
    assert _strip_decoration_refs(markdown, {"other.png"}, set()) == markdown
