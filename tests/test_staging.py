"""Resolving a staging entry that may be a bundle directory."""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._staging import resolve_staged, staged_sources


def _bundle(root: Path, slug: str, ext: str = ".html", *, extras: bool = True) -> Path:
    d = root / slug
    d.mkdir(parents=True)
    (d / f"{slug}{ext}").write_text("<p>x</p>")
    if extras:
        (d / "manifest.json").write_text("{}")
        (d / "images").mkdir()
        (d / "images" / "a.png").write_bytes(b"\x89PNG")
    return d


def test_plain_file_resolves_to_itself(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    assert resolve_staged(f) == f


def test_bundle_resolves_to_its_deliverable(tmp_path: Path) -> None:
    """The deliverable is named after the directory — the upstream contract."""
    d = _bundle(tmp_path, "acme-manual")
    assert resolve_staged(d) == d / "acme-manual.html"


def test_bundle_resolves_for_a_pdf_deliverable(tmp_path: Path) -> None:
    d = _bundle(tmp_path, "acme-spec", ".pdf")
    assert resolve_staged(d) == d / "acme-spec.pdf"


def test_bundle_ignores_sidecars_and_subdirs(tmp_path: Path) -> None:
    """manifest.json / images.json / raw/ must never be mistaken for the source."""
    d = _bundle(tmp_path, "acme-manual")
    (d / "images.json").write_text("[]")
    (d / "raw").mkdir()
    (d / "raw" / "0001.html").write_text("<p>page</p>")
    assert resolve_staged(d) == d / "acme-manual.html"


def test_single_convertible_file_wins_when_not_slug_named(tmp_path: Path) -> None:
    d = tmp_path / "odd-bundle"
    d.mkdir()
    (d / "something-else.pdf").write_bytes(b"%PDF-1.4\n")
    assert resolve_staged(d) == d / "something-else.pdf"


def test_a_sidecar_is_never_chosen_over_the_document(tmp_path: Path) -> None:
    """`.json` is convertible in its own right, so a manifest is a candidate on
    suffix alone — but inside a bundle it is a sidecar, never the deliverable."""
    d = tmp_path / "odd-bundle"
    d.mkdir()
    (d / "something-else.pdf").write_bytes(b"%PDF-1.4\n")
    (d / "manifest.json").write_text("{}")
    (d / "images.json").write_text("[]")
    assert resolve_staged(d) == d / "something-else.pdf"


def test_a_lone_sidecar_is_not_a_document(tmp_path: Path) -> None:
    """The husk case: a partial staging that copied only the manifest. Handing
    it back would convert an acquisition record as if it were the manual."""
    d = tmp_path / "husk"
    d.mkdir()
    (d / "manifest.json").write_text("{}")
    assert resolve_staged(d) is None


def test_qti_export_dir_is_not_resolved_inward(tmp_path: Path) -> None:
    """A QTI export converts as the directory; resolving inward would pick a
    single question file."""
    d = tmp_path / "quiz-export"
    d.mkdir()
    (d / "imsmanifest.xml").write_text("<manifest/>")
    (d / "quiz-export.xml").write_text("<questestinterop/>")
    assert resolve_staged(d) is None


def test_ambiguous_directory_resolves_to_nothing(tmp_path: Path) -> None:
    """Two candidates and no slug-named one: refuse rather than guess."""
    d = tmp_path / "ambiguous"
    d.mkdir()
    (d / "a.pdf").write_bytes(b"%PDF-1.4\n")
    (d / "b.pdf").write_bytes(b"%PDF-1.4\n")
    assert resolve_staged(d) is None


def test_directory_with_no_convertible_file_resolves_to_nothing(tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    (d / "manifest.json").write_text("{}")
    assert resolve_staged(d) is None


def test_output_dir_is_never_treated_as_a_source(tmp_path: Path) -> None:
    """A conversions/out dir holds a *.raw.md; handing one back as a source
    would feed a checkpoint into the pipeline as if it were the original."""
    d = tmp_path / "converted"
    d.mkdir()
    (d / "converted.raw.md").write_text("# x")
    (d / "converted.md").write_text("# x")
    assert resolve_staged(d) is None


def test_symlinked_bundle_resolves_through_the_link(tmp_path: Path) -> None:
    real = _bundle(tmp_path / "upstream", "acme-manual")
    staging = tmp_path / "in"
    staging.mkdir()
    link = staging / "acme-manual"
    link.symlink_to(real)
    assert resolve_staged(link) == link / "acme-manual.html"


def test_staged_sources_mixes_files_and_bundles(tmp_path: Path) -> None:
    _bundle(tmp_path, "bundled-doc")
    (tmp_path / "loose.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    (tmp_path / "notes.txt").write_text("not convertible")
    found = {p.name for p in staged_sources(tmp_path)}
    assert found == {"bundled-doc.html", "loose.pdf"}


def test_staged_sources_skips_dotdirs_and_missing_root(tmp_path: Path) -> None:
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "x.pdf").write_bytes(b"%PDF-1.4\n")
    assert list(staged_sources(tmp_path)) == []
    assert list(staged_sources(tmp_path / "nope")) == []


def test_broken_symlink_is_skipped(tmp_path: Path) -> None:
    """An upstream re-ingest briefly unlinks the deliverable; a dangling entry
    must not crash the scan."""
    (tmp_path / "gone").symlink_to(tmp_path / "does-not-exist")
    assert list(staged_sources(tmp_path)) == []
