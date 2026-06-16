"""Tests for the per-image vision cache (services/_vision_cache.py).

The cache key is the image's perceptual hash (the `<phash>.json` filename).
A cached description is reused whenever that key matches — **regardless of
which engine (backend) or model produced it**. `backend`/`model` are recorded
as provenance only, never as a reuse gate. The only things that invalidate a
cached description are the image content changing (a different phash → a
different file) or an explicit cache delete (`--rerun-from vision` /
`pagespeak invalidate`).
"""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.models._models import Diagram
from pagespeak.services import _vision_cache as vcache


def _write_entry(
    cache_path: Path,
    *,
    backend: str,
    model: str | None,
    caption: str = "A caption.",
    mermaid: str | None = None,
    diagram_type: str | None = None,
) -> None:
    vcache.write(
        cache_path,
        diagram=Diagram(
            image_path=Path("x.png"),
            caption=caption,
            mermaid=mermaid,
            diagram_type=diagram_type,
        ),
        backend=backend,
        model=model,
        phash=cache_path.stem,
        source_paths=["x.png"],
    )


def test_load_returns_none_when_absent(tmp_path: Path) -> None:
    assert vcache.load(tmp_path / "missing.json") is None


def test_load_returns_entry_when_present(tmp_path: Path) -> None:
    p = tmp_path / "abc.json"
    _write_entry(p, backend="claude_code", model="haiku", caption="Hello.")
    hit = vcache.load(p)
    assert hit is not None
    assert hit["caption"] == "Hello."


def test_load_reuses_entry_made_by_a_different_backend(tmp_path: Path) -> None:
    """An entry written under `openrouter` (model null) MUST be reused on a
    later run nominally under `claude_code`/`haiku`: the image hash is the
    key, the engine is not. Re-analyzing it would re-spend on descriptions
    already on disk."""
    p = tmp_path / "phys.json"
    _write_entry(p, backend="openrouter", model=None, caption="Diagram.")
    hit = vcache.load(p)
    assert hit is not None
    assert hit["caption"] == "Diagram."


def test_load_reuses_entry_made_by_a_different_model(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    _write_entry(p, backend="anthropic", model="claude-haiku-4-5", caption="X.")
    assert vcache.load(p) is not None


def test_load_returns_none_on_unreadable_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    assert vcache.load(p) is None


def test_load_returns_none_on_non_dict_json(tmp_path: Path) -> None:
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert vcache.load(p) is None


def test_write_records_backend_and_model_as_provenance(tmp_path: Path) -> None:
    """backend/model are written for inspectability (a human can see which
    engine produced a caption) but do NOT gate reuse."""
    p = tmp_path / "prov.json"
    _write_entry(p, backend="openrouter", model=None)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["backend"] == "openrouter"
    assert data["model"] is None
    assert vcache.load(p) is not None  # still reusable regardless


def test_diagram_from_cache_reconstructs(tmp_path: Path) -> None:
    cached = {
        "caption": "Cap.",
        "mermaid": "flowchart TD\n A-->B",
        "diagram_type": "flowchart",
    }
    d = vcache.diagram_from_cache(cached, Path("img.png"))
    assert d.caption == "Cap."
    assert d.mermaid == "flowchart TD\n A-->B"
    assert d.diagram_type == "flowchart"
    assert d.image_path == Path("img.png")


def test_diagram_from_cache_defaults_caption_when_missing() -> None:
    d = vcache.diagram_from_cache({}, Path("img.png"))
    assert d.caption == "Image at img.png."
