from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagespeak.models._pipeline import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ChunkState,
    Manifest,
    sha256_file,
)


def test_sha256_file_is_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    assert sha256_file(f) == sha256_file(f)


def test_sha256_file_differs_on_content_change(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    h1 = sha256_file(f)
    f.write_bytes(b"y")
    h2 = sha256_file(f)
    assert h1 != h2


def test_load_or_create_initializes_fresh_manifest(tmp_path: Path) -> None:
    src = tmp_path / "input.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    mf = Manifest.load_or_create(out, input_path=src)

    assert (out / MANIFEST_FILENAME).exists()
    assert mf.version == MANIFEST_VERSION
    assert mf.input_sha256 == sha256_file(src)
    assert mf.input_path.endswith("input.pdf")
    assert mf.chunks == []


def test_load_or_create_returns_existing(tmp_path: Path) -> None:
    src = tmp_path / "input.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"

    mf1 = Manifest.load_or_create(out, input_path=src)
    mf1.add_or_update_chunk(ChunkState(page_range="0-9", status="completed"))

    mf2 = Manifest.load_or_create(out, input_path=src)
    assert len(mf2.chunks) == 1
    assert mf2.chunks[0].page_range == "0-9"


def test_load_or_create_rejects_input_mismatch(tmp_path: Path) -> None:
    src1 = tmp_path / "a.pdf"
    src2 = tmp_path / "b.pdf"
    src1.write_bytes(b"first")
    src2.write_bytes(b"second")
    out = tmp_path / "out"

    Manifest.load_or_create(out, input_path=src1)

    with pytest.raises(ValueError, match="fingerprint mismatch"):
        Manifest.load_or_create(out, input_path=src2)


def test_save_is_atomic_no_partial_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    Manifest.load_or_create(out)
    leftovers = list(out.glob(".manifest.*.tmp"))
    assert leftovers == []


def test_save_round_trip_preserves_state(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_chunk_completed("0-9", raw_md="chunks/0-9/raw.md", images=["chunks/0-9/images/a.png"])
    mf.set_vision_config(backend="anthropic", model="claude-haiku-4-5-20251001")
    mf.mark_vision_completed("phash-aaa")

    reloaded = Manifest.load_or_create(out)
    assert reloaded.chunks[0].status == "completed"
    assert reloaded.chunks[0].raw_md == "chunks/0-9/raw.md"
    assert reloaded.vision.backend == "anthropic"
    assert reloaded.vision.completed_image_phashes == ["phash-aaa"]


def test_completed_chunk_ranges_excludes_in_progress(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.add_or_update_chunk(ChunkState(page_range="0-9", status="completed"))
    mf.add_or_update_chunk(ChunkState(page_range="10-19", status="in_progress"))
    mf.add_or_update_chunk(ChunkState(page_range="20-29", status="failed"))
    assert mf.completed_chunk_ranges() == {"0-9"}


def test_mark_chunk_completed_overwrites_failed(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_chunk_failed("0-9", error="surya crash")
    assert mf.chunks[0].status == "failed"
    mf.mark_chunk_completed("0-9", raw_md="chunks/0-9/raw.md", images=[])
    assert mf.chunks[0].status == "completed"
    assert mf.chunks[0].error is None


def test_all_chunk_images_orders_by_page_range(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_chunk_completed(
        "10-19",
        raw_md="chunks/10-19/raw.md",
        images=["chunks/10-19/images/b.png"],
    )
    mf.mark_chunk_completed(
        "0-9",
        raw_md="chunks/0-9/raw.md",
        images=["chunks/0-9/images/a.png"],
    )
    paths = mf.all_chunk_images()
    assert [p.name for p in paths] == ["a.png", "b.png"]


def test_all_chunk_raw_md_skips_incomplete(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_chunk_completed("0-9", raw_md="chunks/0-9/raw.md", images=[])
    mf.add_or_update_chunk(ChunkState(page_range="10-19", status="in_progress"))
    paths = mf.all_chunk_raw_md()
    assert len(paths) == 1
    assert paths[0].name == "raw.md"


def test_vision_completed_set_dedupes(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_vision_completed("phash-1")
    mf.mark_vision_completed("phash-1")
    assert mf.vision_completed_set() == {"phash-1"}
    assert mf.vision.completed_image_phashes == ["phash-1"]


def test_vision_completed_clears_failure(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_vision_failed("phash-x")
    assert mf.vision.failed_image_phashes == ["phash-x"]
    mf.mark_vision_completed("phash-x")
    assert mf.vision.failed_image_phashes == []
    assert mf.vision_completed_set() == {"phash-x"}


def test_manifest_json_is_human_readable(tmp_path: Path) -> None:
    out = tmp_path / "out"
    mf = Manifest.load_or_create(out)
    mf.mark_chunk_completed("0-9", raw_md="chunks/0-9/raw.md", images=[])
    text = (out / MANIFEST_FILENAME).read_text(encoding="utf-8")
    # Indented + sorted-ish; readable for a human eyeballing the file.
    assert "\n  " in text
    data = json.loads(text)
    assert data["version"] == MANIFEST_VERSION
    assert data["chunks"][0]["page_range"] == "0-9"


def test_manifest_load_refuses_v2(tmp_path: Path) -> None:
    """Bumps schema to v3. v2 manifests must error with a
    clear message pointing to --force or rm -rf."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "input_path": "/x/y.pdf",
                "input_sha256": "abc",
                "chunks": [],
                "vision": {},
                "stitch": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        Manifest.load_or_create(out)

    msg = str(excinfo.value)
    assert "v2" in msg or "version 2" in msg.lower()
    assert "--force" in msg or "rm -rf" in msg


def test_manifest_load_accepts_v3(tmp_path: Path) -> None:
    """v3 manifests load cleanly."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "version": 3,
                "input_path": "/x/y.pdf",
                "input_sha256": "abc",
                "chunks": [],
                "vision": {},
            }
        ),
        encoding="utf-8",
    )

    mf = Manifest.load_or_create(out)
    assert mf.version == 3
    assert mf.input_sha256 == "abc"


def test_manifest_to_dict_omits_consolidated_md_when_unset(tmp_path: Path) -> None:
    """v3 drops the `stitch` block entirely."""
    mf = Manifest(output_dir=tmp_path)
    data = mf.to_dict()
    # Schema v3 should not have a 'stitch' key at all.
    assert "stitch" not in data
    assert data["version"] == 3
