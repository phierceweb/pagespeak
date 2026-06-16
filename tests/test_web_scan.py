from __future__ import annotations

from pagespeak.web._config import WebConfig
from pagespeak.web._scan import (
    PHASES,
    Conversion,
    get_conversion,
    scan_conversions,
    slugify,
)


def _cfg(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    return WebConfig(conversions_dir=tmp_path, host="h", port=1, concurrency=1)


def test_slugify():
    assert slugify("Adat_Manual") == "adat-manual"
    assert slugify("Dimmer Controls") == "dimmer-controls"
    assert slugify("A Product Reference Guide") == "a-product-reference-guide"


def test_scan_links_source_to_handnamed_out_dir(tmp_path):
    cfg = _cfg(tmp_path)
    out = cfg.out_dir / "sample-manual"
    out.mkdir()
    (out / "sample_manual.raw.md").write_text("# raw", encoding="utf-8")
    (out / "sample_manual.md").write_text("# final", encoding="utf-8")
    (cfg.in_dir / "sample_manual.pdf").write_text("x", encoding="utf-8")

    convs = scan_conversions(cfg)
    assert len(convs) == 1
    c = convs[0]
    assert c.dir_name == "sample-manual"
    assert c.stem == "sample_manual"
    assert c.source_path == cfg.in_dir / "sample_manual.pdf"
    assert c.phases_done["ingest"] is True
    assert c.phases_done["final"] is True
    assert c.phases_done["vision"] is False


def test_scan_includes_unconverted_source(tmp_path):
    cfg = _cfg(tmp_path)
    (cfg.in_dir / "New Manual.pdf").write_text("x", encoding="utf-8")

    convs = scan_conversions(cfg)
    assert len(convs) == 1
    c = convs[0]
    assert c.dir_name == "new-manual"
    assert c.source_path == cfg.in_dir / "New Manual.pdf"
    assert c.stem is None
    assert all(v is False for v in c.phases_done.values())


def test_scan_counts_images_and_sections(tmp_path):
    cfg = _cfg(tmp_path)
    out = cfg.out_dir / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")
    (out / "Doc.cleaned.md").write_text("# c", encoding="utf-8")
    imgs = out / "images"
    imgs.mkdir()
    (imgs / "p1.png").write_bytes(b"x")
    (imgs / "p2.jpg").write_bytes(b"x")
    (out / "sections").mkdir()

    c = get_conversion(cfg, "doc")
    assert c is not None
    assert c.image_count == 2
    assert c.phases_done["cleanup"] is True
    assert c.phases_done["split"] is True
    assert PHASES[0] == "ingest"


def test_get_conversion_missing(tmp_path):
    cfg = _cfg(tmp_path)
    assert get_conversion(cfg, "nope") is None
    assert isinstance(Conversion, type)
