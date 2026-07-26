from __future__ import annotations

from pagespeak.web._config import WebConfig
from pagespeak.web._scan import (
    PHASES,
    Conversion,
    get_conversion,
    safe_out_dir,
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


def test_safe_out_dir_rejects_escapes_and_the_root_itself(tmp_path):
    """`.` resolved to the out root, yielding a Conversion standing for every conversion."""
    cfg = _cfg(tmp_path)
    (cfg.out_dir / "doc").mkdir()

    assert safe_out_dir(cfg, "doc") == (cfg.out_dir / "doc").resolve()
    assert safe_out_dir(cfg, ".") is None
    assert safe_out_dir(cfg, "") is None
    assert safe_out_dir(cfg, "..") is None
    assert safe_out_dir(cfg, "../in") is None


def _stage_bundle(cfg, slug, ext=".html"):
    """A staged bundle: a directory holding the deliverable plus its sidecars."""
    d = cfg.in_dir / slug
    d.mkdir()
    (d / f"{slug}{ext}").write_text("<p>x</p>", encoding="utf-8")
    (d / "manifest.json").write_text("{}", encoding="utf-8")
    (d / "images").mkdir()
    return d / f"{slug}{ext}"


def test_scan_lists_a_bundle_staged_source(tmp_path):
    """A bundle is a directory, so the old is_file() filter hid it entirely."""
    cfg = _cfg(tmp_path)
    _stage_bundle(cfg, "acme-manual")
    convs = scan_conversions(cfg)
    assert [c.dir_name for c in convs] == ["acme-manual"]
    assert convs[0].source_path.name == "acme-manual.html"


def test_scan_links_an_out_dir_to_its_bundle_source(tmp_path):
    cfg = _cfg(tmp_path)
    _stage_bundle(cfg, "acme-manual")
    out = cfg.out_dir / "acme-manual"
    out.mkdir()
    (out / "acme-manual.raw.md").write_text("# raw", encoding="utf-8")
    conv = scan_conversions(cfg)[0]
    assert conv.source_path is not None, "out dir shows no linked source"
    assert conv.source_path.name == "acme-manual.html"


def test_scan_links_through_a_symlinked_bundle(tmp_path):
    """The real staging shape: conversions/in/<slug> -> an upstream bundle."""
    cfg = _cfg(tmp_path)
    upstream = tmp_path / "upstream" / "acme-manual"
    upstream.mkdir(parents=True)
    (upstream / "acme-manual.pdf").write_bytes(b"%PDF-1.4\n")
    (upstream / "manifest.json").write_text("{}", encoding="utf-8")
    (cfg.in_dir / "acme-manual").symlink_to(upstream)
    convs = scan_conversions(cfg)
    assert [c.dir_name for c in convs] == ["acme-manual"]
    assert convs[0].source_path.name == "acme-manual.pdf"


def test_scan_does_not_double_list_a_converted_bundle(tmp_path):
    cfg = _cfg(tmp_path)
    _stage_bundle(cfg, "acme-manual")
    out = cfg.out_dir / "acme-manual"
    out.mkdir()
    (out / "acme-manual.raw.md").write_text("# raw", encoding="utf-8")
    assert len(scan_conversions(cfg)) == 1


def test_scan_ignores_a_husk_bundle(tmp_path):
    """A partial staging that copied only the manifest is not a document."""
    cfg = _cfg(tmp_path)
    d = cfg.in_dir / "husk"
    d.mkdir()
    (d / "manifest.json").write_text("{}", encoding="utf-8")
    assert scan_conversions(cfg) == []
