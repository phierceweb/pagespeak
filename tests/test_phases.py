"""1:1 mirror of `orchestrators/_phases.py` — exercises the concrete
phases (and their `_load_input` checkpoint hydration) end-to-end via
`to_markdown` single-phase / `start` / `stop_after`. Dir-mode, offline
(no backend, no diagrams) so the pipeline is deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak import to_markdown

RAW = "# Doc Title\n\nIntro para.\n\n## A Section\n\nBody of A.\n\n## B Section\n\nBody of B.\n"


def _seed(tmp_path: Path) -> Path:
    """A dir-mode output dir with just a raw.md checkpoint."""
    (tmp_path / "doc.raw.md").write_text(RAW, encoding="utf-8")
    return tmp_path


def test_stop_after_cleanup_writes_cleaned_not_normalized(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="cleanup")
    assert (d / "doc.cleaned.md").exists()
    assert not (d / "doc.normalized.md").exists()


def test_stop_after_normalize_writes_through_normalized_only(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="normalize")
    assert (d / "doc.cleaned.md").exists()
    assert (d / "doc.normalized.md").exists()
    assert not (d / "doc.repaired.md").exists()  # repair is after normalize
    assert not (d / "doc.visioned.md").exists()


def test_stop_after_repair_writes_repaired_not_structured(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="repair")
    assert (d / "doc.normalized.md").exists()
    assert (d / "doc.repaired.md").exists()  # repair's own checkpoint
    assert not (d / "doc.structured.md").exists()
    assert not (d / "doc.visioned.md").exists()


def test_stop_after_structure_writes_structured_not_visioned(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="structure")
    assert (d / "doc.repaired.md").exists()
    assert (d / "doc.structured.md").exists()  # structure's own checkpoint
    assert not (d / "doc.visioned.md").exists()


def test_no_stop_after_runs_full_pipeline(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False)
    assert (d / "doc.cleaned.md").exists()
    assert (d / "doc.normalized.md").exists()
    assert (d / "doc.repaired.md").exists()
    assert (d / "doc.structured.md").exists()
    assert (d / "doc.visioned.md").exists()


def test_start_at_vision_loads_structured_checkpoint(tmp_path: Path) -> None:
    """Run through structure first (stop_after=structure), then start a
    fresh call at `vision`: it must hydrate from structured.md (vision's
    input checkpoint since the structure phase landed) and still produce
    its visioned output."""
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="structure")
    structured = (d / "doc.structured.md").read_text(encoding="utf-8")
    (d / "doc.visioned.md").unlink(missing_ok=True)

    res = to_markdown(d, output_dir=d, diagrams=False, start="vision")
    assert (d / "doc.visioned.md").exists()
    # vision ran on the structured checkpoint content
    assert res.markdown  # non-empty
    # structured.md is the input; vision (no diagrams) shouldn't rewrite it
    assert (d / "doc.structured.md").read_text(encoding="utf-8") == structured


def test_vision_phase_feeds_source_alt_to_gather(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vision phase must extract each figure's existing alt text from the
    structured checkpoint and pass it to gather_diagrams (the alt-aware
    prompt's input)."""
    import pagespeak.services._diagrams as diag_mod

    d = _seed(tmp_path)  # doc.raw.md → stem detection
    (d / "doc.structured.md").write_text(
        "# Doc\n\n![Original source alt for pic](images/pic.webp)\n",
        encoding="utf-8",
    )
    # do_vision requires images present under out/images/ (gather is faked,
    # so the bytes don't matter — only that the glob finds the file).
    (d / "images").mkdir()
    (d / "images" / "pic.webp").write_bytes(b"not-a-real-image")
    captured: dict[str, object] = {}

    def _fake_gather(images: object, **kwargs: object) -> dict:
        captured["alt_by_basename"] = kwargs.get("alt_by_basename")
        return {}

    monkeypatch.setattr(diag_mod, "gather_diagrams", _fake_gather)
    to_markdown(d, output_dir=d, diagrams=True, start="vision", stop_after="vision")
    assert captured["alt_by_basename"] == {"pic.webp": "Original source alt for pic"}


def test_vision_phase_degrades_missing_image_ref(tmp_path: Path) -> None:
    """VisionPhase degrades an image ref whose local target is missing on disk
    into an italic caption — even with diagrams OFF — so a broken
    `![alt](missing)` link becomes the RAG-usable alt text in the checkpoint
    (and thus the master + split sections). No `images/missing.webp` on disk."""
    d = _seed(tmp_path)  # doc.raw.md → stem detection
    (d / "doc.structured.md").write_text(
        "# Doc\n\n![a chart of the missing figure](images/missing.webp)\n",
        encoding="utf-8",
    )
    to_markdown(d, output_dir=d, diagrams=False, start="vision", stop_after="vision")
    visioned = (d / "doc.visioned.md").read_text(encoding="utf-8")
    assert "![a chart of the missing figure]" not in visioned  # broken ref gone
    assert "_a chart of the missing figure_" in visioned  # degraded to a caption


def test_single_phase_start_equals_stop(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="cleanup")
    cleaned_before = (d / "doc.cleaned.md").read_text(encoding="utf-8")
    # Re-run ONLY cleanup: start==stop=="cleanup".
    to_markdown(d, output_dir=d, diagrams=False, start="cleanup", stop_after="cleanup")
    assert (d / "doc.cleaned.md").read_text(encoding="utf-8") == cleaned_before
    # downstream still absent — single phase didn't run them
    assert not (d / "doc.normalized.md").exists()


def test_unknown_stop_after_stage_raises(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    with pytest.raises(ValueError):
        to_markdown(d, output_dir=d, diagrams=False, stop_after="bogus")


def test_stop_after_vision_writes_visioned_checkpoint(tmp_path: Path) -> None:
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="vision")
    assert (d / "doc.normalized.md").exists()
    assert (d / "doc.visioned.md").exists()  # vision's own checkpoint
    assert not (d / "sections").exists()  # split did not run


def test_from_split_reads_visioned_checkpoint(tmp_path: Path) -> None:
    """`--from split` must hydrate from visioned.md (vision's own
    checkpoint). Prove it with a sentinel: overwrite visioned.md, start
    at split, the sentinel must reach the output."""
    d = _seed(tmp_path)
    to_markdown(d, output_dir=d, diagrams=False, stop_after="vision")
    (d / "doc.visioned.md").write_text(
        "# Doc\n\n# 1. Alpha\n\n"
        "ALPHA-SENTINEL body long enough to clear the min-body filter here.\n\n"
        "# 2. Beta\n\nbeta section body also long enough to be kept as a file.\n",
        encoding="utf-8",
    )
    to_markdown(
        d, output_dir=d, diagrams=False, start="split", split_sections=True, min_body_chars=0
    )
    sections = d / "sections"
    assert sections.exists()
    blob = "\n".join(p.read_text(encoding="utf-8") for p in sections.rglob("*.md"))
    assert "ALPHA-SENTINEL" in blob  # split consumed visioned.md


def test_from_cleanup_reruns_not_resumes(tmp_path: Path) -> None:
    """`--from cleanup` must RE-RUN cleanup, not silently reuse a cached
    `cleaned.md`. The resume-from-cleaned shortcut exists for the normal
    full run; when cleanup is the EXPLICIT start phase, reusing the cache
    makes per-stage iteration (the whole point of `--from`) a no-op."""
    d = _seed(tmp_path)
    # First run produces a real cleaned.md + run.json.
    to_markdown(d, output_dir=d, diagrams=False, stop_after="cleanup")
    # Simulate a stale cached cleaned.md — e.g. left over from before a
    # cleanup-code change the dev is now trying to test.
    sentinel = "# STALE CACHED CONTENT CLEANUP WOULD NEVER PRODUCE\n"
    (d / "doc.cleaned.md").write_text(sentinel, encoding="utf-8")
    # Re-run ONLY cleanup. It must regenerate cleaned.md from raw.md.
    to_markdown(d, output_dir=d, diagrams=False, start="cleanup", stop_after="cleanup")
    cleaned = (d / "doc.cleaned.md").read_text(encoding="utf-8")
    assert "STALE CACHED CONTENT" not in cleaned, "cleanup resumed the stale cache"
    assert "Doc Title" in cleaned  # real content, re-derived from raw.md


# --- cleanup localizes remote images for markdown/dir-mode sources ----------

_PNG = b"\x89PNG\r\n\x1a\n" + b"body"


class _FakeResp:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.is_redirect = False

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self._r = responses

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def get(self, url: str) -> _FakeResp:
        return _FakeResp(self._r[url])


def test_cleanup_localizes_remote_images_for_markdown_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A markdown/dir-mode source skips ingest (where HTML's image download
    lives), so its remote image refs are still remote at cleanup. Cleanup must
    pull them local + retarget so the vision pass can see them."""
    monkeypatch.delenv("PAGESPEAK_DOWNLOAD_REMOTE_IMAGES", raising=False)
    md = "# Doc\n\n![fig](https://cdn.x.com/images/a.png)\n\n## Sec\n\nBody.\n"
    (tmp_path / "doc.raw.md").write_text(md, encoding="utf-8")
    monkeypatch.setattr(
        "pagespeak.backends._remote_images.httpx.Client",
        lambda *a, **k: _FakeClient({"https://cdn.x.com/images/a.png": _PNG}),
    )
    monkeypatch.setattr("pagespeak.backends._remote_images._host_is_blocked", lambda host: False)

    to_markdown(tmp_path, output_dir=tmp_path, diagrams=False, stop_after="cleanup")

    cleaned = (tmp_path / "doc.cleaned.md").read_text(encoding="utf-8")
    assert "](images/a.png)" in cleaned  # retargeted to local
    assert "https://" not in cleaned  # remote ref gone
    assert (tmp_path / "images" / "a.png").read_bytes() == _PNG


def test_cleanup_image_download_respects_disable_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAGESPEAK_DOWNLOAD_REMOTE_IMAGES", "0")
    md = "# Doc\n\n![fig](https://cdn.x.com/images/a.png)\n"
    (tmp_path / "doc.raw.md").write_text(md, encoding="utf-8")

    to_markdown(tmp_path, output_dir=tmp_path, diagrams=False, stop_after="cleanup")

    cleaned = (tmp_path / "doc.cleaned.md").read_text(encoding="utf-8")
    assert "](https://cdn.x.com/images/a.png)" in cleaned  # left remote
    assert not (tmp_path / "images").exists()
