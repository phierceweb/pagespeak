from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._rerun import (
    RERUN_STAGES,
    files_to_invalidate,
    invalidate_caches,
)


def _populate(out: Path, stem: str = "doc") -> dict[str, Path]:
    """Create a full set of cache artifacts. Returns the mapping for
    asserting which were deleted."""
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.raw.md").write_text("raw")
    (out / "images").mkdir()
    (out / "images" / "image1.png").write_text("png")
    (out / f"{stem}.cleaned.md").write_text("cleaned")
    (out / f"{stem}.normalized.md").write_text("normalized")
    (out / ".heading-normalize-cache").mkdir()
    (out / ".heading-normalize-cache" / "x.json").write_text("{}")
    (out / ".vision-cache").mkdir()
    (out / ".vision-cache" / "abc.json").write_text("{}")
    (out / ".decoration-cache").mkdir()
    (out / ".decoration-cache" / "def.json").write_text("{}")
    (out / "sections").mkdir()
    (out / "sections" / "Intro.md").write_text("# Intro")
    (out / "INDEX.md").write_text("# INDEX")
    return {
        "raw": out / f"{stem}.raw.md",
        "images": out / "images",
        "cleaned": out / f"{stem}.cleaned.md",
        "normalized": out / f"{stem}.normalized.md",
        "normalize-cache": out / ".heading-normalize-cache",
        "vision-cache": out / ".vision-cache",
        "decoration-cache": out / ".decoration-cache",
        "sections": out / "sections",
        "index": out / "INDEX.md",
    }


def test_rerun_stages_are_ingest_through_split() -> None:
    assert RERUN_STAGES == (
        "ingest",
        "cleanup",
        "decorations",
        "normalize",
        "repair",
        "structure",
        "vision",
        "split",
    )


def test_rerun_decorations_busts_cache_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / ".decoration-cache").mkdir()
    (out / ".decoration-cache" / "abc.json").write_text("{}", encoding="utf-8")
    (out / "doc.normalized.md").write_text("x", encoding="utf-8")
    # normalize is downstream of decorations — its content-keyed cache must survive.
    (out / ".heading-normalize-cache").mkdir()
    (out / ".heading-normalize-cache" / "y.json").write_text("{}", encoding="utf-8")

    deleted = invalidate_caches(out, "decorations", "doc")
    paths = {str(p.relative_to(out)) for p in deleted}
    assert ".decoration-cache" in paths
    # Downstream structural file also gone:
    assert "doc.normalized.md" in paths
    # Downstream content-keyed cache is PRESERVED:
    assert ".heading-normalize-cache" not in paths
    assert (out / ".heading-normalize-cache").exists()


def test_files_to_invalidate_ingest_preserves_content_keyed_caches(tmp_path: Path) -> None:
    """--rerun-from ingest busts structural files only; content-keyed
    caches (.vision-cache, .heading-normalize-cache) are PRESERVED.
    `pre-normalize.md` was dropped from the registry — it was
    byte-identical to `cleaned.md`."""
    paths = files_to_invalidate(tmp_path, "ingest", "doc")
    names = {p.name for p in paths}
    assert names == {
        "doc.raw.md",
        "images",
        "chunks",
        "manifest.json",
        "doc.cleaned.md",
        "doc.normalized.md",
        "doc.repaired.md",
        "doc.structured.md",
        "doc.visioned.md",
        "sections",
        "INDEX.md",
    }
    assert ".vision-cache" not in names
    assert ".heading-normalize-cache" not in names


def test_files_to_invalidate_split_only_split_files(tmp_path: Path) -> None:
    paths = files_to_invalidate(tmp_path, "split", "doc")
    names = {p.name for p in paths}
    assert names == {"sections", "INDEX.md"}


def test_files_to_invalidate_normalize_preserves_vision_cache(tmp_path: Path) -> None:
    """--rerun-from normalize busts normalize cache + structural
    files plus downstream structural (sections, INDEX.md). Vision moved
    downstream of normalize — vision-cache is preserved (downstream
    content-keyed). dropped `pre-normalize.md`."""
    paths = files_to_invalidate(tmp_path, "normalize", "doc")
    names = {p.name for p in paths}
    assert names == {
        ".heading-normalize-cache",
        "doc.normalized.md",
        "doc.repaired.md",
        "doc.structured.md",
        "doc.visioned.md",
        "sections",
        "INDEX.md",
    }
    assert ".vision-cache" not in names


def test_files_to_invalidate_vision_busts_vision_cache_only(tmp_path: Path) -> None:
    """--rerun-from vision busts its own structural checkpoint
    (visioned.md) + its own content-keyed cache (.vision-cache)
    plus downstream structural (sections, INDEX.md). Normalize artifacts
    upstream — preserved."""
    paths = files_to_invalidate(tmp_path, "vision", "doc")
    names = {p.name for p in paths}
    assert names == {
        "doc.visioned.md",
        ".vision-cache",
        "sections",
        "INDEX.md",
    }
    assert "doc.normalized.md" not in names
    assert "doc.repaired.md" not in names  # upstream of vision — preserved
    assert ".heading-normalize-cache" not in names


def test_files_to_invalidate_repair_busts_repaired_and_downstream(tmp_path: Path) -> None:
    """--rerun-from repair busts its own structural checkpoint
    (repaired.md) plus downstream structural (visioned.md, sections,
    INDEX.md). Repair has no content-keyed cache; the downstream
    .vision-cache is preserved."""
    paths = files_to_invalidate(tmp_path, "repair", "doc")
    names = {p.name for p in paths}
    assert names == {
        "doc.repaired.md",
        "doc.structured.md",
        "doc.visioned.md",
        "sections",
        "INDEX.md",
    }
    assert ".vision-cache" not in names
    assert "doc.normalized.md" not in names  # upstream — preserved


def test_files_to_invalidate_structure_busts_structured_and_downstream(tmp_path: Path) -> None:
    """--rerun-from structure busts its own structural checkpoint
    (structured.md) plus downstream structural (visioned.md, sections,
    INDEX.md). Structure has no content-keyed cache; the downstream
    .vision-cache is preserved (content-keyed, downstream)."""
    paths = files_to_invalidate(tmp_path, "structure", "doc")
    names = {p.name for p in paths}
    assert names == {
        "doc.structured.md",
        "doc.visioned.md",
        "sections",
        "INDEX.md",
    }
    assert ".vision-cache" not in names
    assert "doc.repaired.md" not in names  # upstream — preserved
    assert "doc.normalized.md" not in names


def test_files_to_invalidate_unknown_stage_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown rerun stage"):
        files_to_invalidate(tmp_path, "bogus", "doc")  # type: ignore[arg-type]


def test_invalidate_caches_ingest_preserves_content_keyed_caches(tmp_path: Path) -> None:
    """--rerun-from ingest deletes structural files but leaves both
    content-keyed caches alive."""
    files = _populate(tmp_path)
    deleted = invalidate_caches(tmp_path, "ingest", "doc")
    # 6 structural deletions: raw, images, cleaned, normalized, sections, INDEX.
    # chunks and manifest.json are also downstream structural files of
    # `ingest` but don't exist in this fixture (single-shot output), so
    # they are silent no-ops — the count stays 6.
    assert len(deleted) == 6
    assert not files["raw"].exists()
    assert not files["images"].exists()
    assert not files["cleaned"].exists()
    assert not files["normalized"].exists()
    assert not files["sections"].exists()
    assert not files["index"].exists()
    # Content-keyed caches SURVIVE.
    assert files["vision-cache"].exists()
    assert files["normalize-cache"].exists()
    assert files["decoration-cache"].exists()


def test_invalidate_caches_cleanup_preserves_upstream(tmp_path: Path) -> None:
    """--rerun-from cleanup: cleaned.md + downstream structural files
    are gone; backend stays; both content-keyed caches stay."""
    files = _populate(tmp_path)
    invalidate_caches(tmp_path, "cleanup", "doc")
    assert files["raw"].exists()
    assert files["images"].exists()
    assert not files["cleaned"].exists()
    assert not files["normalized"].exists()
    assert not files["sections"].exists()
    assert not files["index"].exists()
    # Content-keyed caches preserved.
    assert files["normalize-cache"].exists()
    assert files["vision-cache"].exists()
    assert files["decoration-cache"].exists()


def test_invalidate_caches_normalize_preserves_cleanup_and_vision(tmp_path: Path) -> None:
    """--rerun-from normalize busts normalize's content-keyed
    cache + structural normalized.md + downstream split artifacts.
    Cleanup artifacts upstream and .vision-cache downstream-content-keyed
    — both preserved. `pre-normalize.md` is no longer in the registry."""
    files = _populate(tmp_path)
    invalidate_caches(tmp_path, "normalize", "doc")
    assert files["raw"].exists()
    assert files["images"].exists()
    assert files["cleaned"].exists()
    assert files["vision-cache"].exists()
    assert not files["normalize-cache"].exists()
    assert not files["normalized"].exists()
    assert not files["sections"].exists()
    assert not files["index"].exists()


def test_invalidate_caches_vision_preserves_normalize(tmp_path: Path) -> None:
    """--rerun-from vision busts vision cache + downstream
    structural (sections, INDEX). All upstream stages preserved —
    re-running vision doesn't redo normalize."""
    files = _populate(tmp_path)
    invalidate_caches(tmp_path, "vision", "doc")
    assert files["raw"].exists()
    assert files["images"].exists()
    assert files["cleaned"].exists()
    assert files["normalized"].exists()
    assert files["normalize-cache"].exists()
    assert not files["vision-cache"].exists()
    assert not files["sections"].exists()
    assert not files["index"].exists()


def test_invalidate_caches_split_preserves_everything_else(tmp_path: Path) -> None:
    files = _populate(tmp_path)
    invalidate_caches(tmp_path, "split", "doc")
    assert files["raw"].exists()
    assert files["cleaned"].exists()
    assert files["normalized"].exists()
    assert files["normalize-cache"].exists()
    assert files["vision-cache"].exists()
    assert not files["sections"].exists()
    assert not files["index"].exists()


def test_invalidate_caches_silently_skips_missing(tmp_path: Path) -> None:
    """Empty output dir → no errors, no deletions."""
    tmp_path.mkdir(exist_ok=True)
    deleted = invalidate_caches(tmp_path, "split", "doc")
    assert deleted == []


def test_invalidate_caches_nonexistent_output_dir_returns_empty(tmp_path: Path) -> None:
    """`output_dir` doesn't exist at all → return [] gracefully, don't
    raise."""
    missing = tmp_path / "does-not-exist"
    result = invalidate_caches(missing, "split", "doc")
    assert result == []


def test_rerun_from_normalize_busts_visioned_and_downstream(tmp_path) -> None:
    from pagespeak.services._rerun import files_to_invalidate

    (tmp_path / "doc.normalized.md").write_text("x")
    (tmp_path / "doc.visioned.md").write_text("x")
    names = {p.name for p in files_to_invalidate(tmp_path, "normalize", "doc")}
    assert "doc.normalized.md" in names  # own structural file
    assert "doc.visioned.md" in names  # downstream → cascaded
