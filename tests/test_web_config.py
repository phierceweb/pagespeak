from __future__ import annotations

from pathlib import Path

from pagespeak.web._config import WebConfig, load_config


def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("PAGESPEAK_CONVERSIONS_DIR", raising=False)
    monkeypatch.delenv("PAGESPEAK_WEB_HOST", raising=False)
    monkeypatch.delenv("PAGESPEAK_WEB_PORT", raising=False)
    monkeypatch.delenv("PAGESPEAK_WEB_CONCURRENCY", raising=False)
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.conversions_dir == tmp_path / "conversions"
    assert cfg.in_dir == tmp_path / "conversions" / "in"
    assert cfg.out_dir == tmp_path / "conversions" / "out"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8810
    assert cfg.concurrency == 1


def test_load_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGESPEAK_CONVERSIONS_DIR", str(tmp_path / "conv"))
    monkeypatch.setenv("PAGESPEAK_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("PAGESPEAK_WEB_PORT", "9000")
    monkeypatch.setenv("PAGESPEAK_WEB_CONCURRENCY", "3")

    cfg = load_config()

    assert cfg.conversions_dir == tmp_path / "conv"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.concurrency == 3


def test_webconfig_is_frozen():
    cfg = WebConfig(conversions_dir=Path("/x"), host="h", port=1, concurrency=1)
    try:
        cfg.host = "y"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("WebConfig should be frozen")
