from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pagespeak.backends._remote_images import (
    _is_image_url,
    _local_name,
    _remote_image_timeout_s,
    download_remote_images,
    download_remote_images_enabled,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"


# ── Fake httpx client ──────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.is_redirect = False

    def raise_for_status(self) -> None:  # always 200 in the happy path
        return None


class _FakeClient:
    """Stands in for httpx.Client. `responses` maps url → bytes | Exception."""

    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def get(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        r = self._responses[url]
        if isinstance(r, Exception):
            raise r
        return _FakeResponse(r)


def _patch_client(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, bytes | Exception]
) -> _FakeClient:
    client = _FakeClient(responses)
    monkeypatch.setattr(
        "pagespeak.backends._remote_images.httpx.Client",
        lambda *a, **k: client,
    )
    # The mocked tests use safe public URLs; bypass the SSRF DNS resolution so
    # they stay network-free (the guard itself is covered by the SSRF tests).
    monkeypatch.setattr("pagespeak.backends._remote_images._host_is_blocked", lambda host: False)
    return client


# ── _local_name ────────────────────────────────────────────────────────────


def test_local_name_joins_segments_after_images() -> None:
    url = "https://docs.example.com/product/en/images/getting-started/interface.png"
    assert _local_name(url) == "getting-started-interface.png"


def test_local_name_falls_back_to_last_two_segments() -> None:
    url = "https://cdn.example.com/assets/figure.png"
    assert _local_name(url) == "assets-figure.png"


def test_local_name_collision_resistant_across_subpaths() -> None:
    a = "https://x.com/images/eq/gain.png"
    b = "https://x.com/images/global-controls/gain.png"
    assert _local_name(a) != _local_name(b)


# ── _is_image_url ──────────────────────────────────────────────────────────


def test_is_image_url_true_for_image_extensions() -> None:
    assert _is_image_url("https://x.com/a.png")
    assert _is_image_url("https://x.com/a.SVG")


def test_is_image_url_false_for_non_image() -> None:
    assert not _is_image_url("https://x.com/page.html")
    assert not _is_image_url("https://x.com/style.css")


def test_is_image_url_true_for_extensionless_cdn_url() -> None:
    # Some help sites serve figures at extensionless opaque CDN URLs;
    # a markdown `![]()` ref already guarantees image intent, so accept them.
    assert _is_image_url("https://cdn.example.com/assets/v2/web/3609db94-21bc")
    assert _is_image_url("https://cdn.example.com/img/abc123")


# ── download_remote_images ─────────────────────────────────────────────────


def test_download_noop_without_remote_refs(tmp_path: Path) -> None:
    md = "# Doc\n\n![local](images/foo.png)\n\nNo remote refs here.\n"
    out, saved = download_remote_images(md, tmp_path)
    assert out == md
    assert saved == []
    # No client opened, no images/ dir created.
    assert not (tmp_path / "images").exists()


def test_download_pulls_images_and_retargets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = (
        "# Doc\n\n"
        "![a](https://docs.x.com/images/getting-started/a.png)\n\n"
        "![b](https://docs.x.com/images/eq/b.png)\n"
    )
    _patch_client(
        monkeypatch,
        {
            "https://docs.x.com/images/getting-started/a.png": _PNG,
            "https://docs.x.com/images/eq/b.png": _PNG,
        },
    )
    out, saved = download_remote_images(md, tmp_path)

    assert {p.name for p in saved} == {"getting-started-a.png", "eq-b.png"}
    for p in saved:
        assert p.exists()
        assert p.parent == tmp_path / "images"
        assert p.read_bytes() == _PNG

    assert "](images/getting-started-a.png)" in out
    assert "](images/eq-b.png)" in out
    assert "https://" not in out


def test_download_skips_non_image_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = "![link](https://x.com/page.html)\n![img](https://x.com/images/p.png)\n"
    client = _patch_client(monkeypatch, {"https://x.com/images/p.png": _PNG})
    out, saved = download_remote_images(md, tmp_path)

    assert client.calls == ["https://x.com/images/p.png"]
    assert {p.name for p in saved} == {"p.png"}
    # Non-image remote URL is left untouched.
    assert "](https://x.com/page.html)" in out


def test_download_extensionless_url_sniffs_png_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extensionless CDN image URL (some help sites) is downloaded and given a
    real extension sniffed from the bytes, so the ref + vision media-type are
    correct."""
    url = "https://cdn.example.com/assets/v2/web/abc123"
    md = f"![fig]({url})\n"
    _patch_client(monkeypatch, {url: _PNG})
    out, saved = download_remote_images(md, tmp_path)

    assert {p.name for p in saved} == {"web-abc123.png"}
    assert (tmp_path / "images" / "web-abc123.png").read_bytes() == _PNG
    assert "](images/web-abc123.png)" in out
    assert "cdn.example.com" not in out


def test_download_extensionless_url_sniffs_jpeg_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://cdn.example.com/assets/v2/web/jpgone"
    md = f"![fig]({url})\n"
    _patch_client(monkeypatch, {url: b"\xff\xd8\xff\xe0" + b"jfif-body"})
    out, saved = download_remote_images(md, tmp_path)

    assert {p.name for p in saved} == {"web-jpgone.jpg"}
    assert "](images/web-jpgone.jpg)" in out


def test_download_reuses_extensionless_sniffed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://cdn.example.com/assets/v2/web/cached1"
    md = f"![c]({url})\n"
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "web-cached1.png").write_bytes(_PNG)

    client = _patch_client(monkeypatch, {})  # any fetch would KeyError
    out, saved = download_remote_images(md, tmp_path)

    assert client.calls == []  # the already-sniffed local file is reused
    assert {p.name for p in saved} == {"web-cached1.png"}
    assert "](images/web-cached1.png)" in out


def test_download_keeps_remote_ref_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = "https://x.com/images/ok.png"
    bad = "https://x.com/images/forbidden.png"
    md = f"![ok]({good})\n![no]({bad})\n"
    _patch_client(
        monkeypatch,
        {good: _PNG, bad: httpx.RequestError("403 Forbidden")},
    )
    out, saved = download_remote_images(md, tmp_path)

    assert {p.name for p in saved} == {"ok.png"}
    assert "](images/ok.png)" in out
    # Failed download keeps its remote URL so the ref still resolves.
    assert f"]({bad})" in out


def test_download_reuses_existing_file_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://x.com/images/cached.png"
    md = f"![c]({url})\n"
    # Pre-seed the local file.
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "cached.png").write_bytes(_PNG)

    client = _patch_client(monkeypatch, {})  # empty: any .get would KeyError
    out, saved = download_remote_images(md, tmp_path)

    assert client.calls == []  # no network call for a cached file
    assert "](images/cached.png)" in out
    assert {p.name for p in saved} == {"cached.png"}


# ── base_url: resolve relative HTML refs ───────────────────────────────────


def test_download_resolves_relative_ref_against_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = "# Doc\n\n![fig](../Storage/pub/topic/fig.png)\n"
    base = "https://site.com/manual/HTML/welcome.html"
    resolved = "https://site.com/manual/Storage/pub/topic/fig.png"
    client = _patch_client(monkeypatch, {resolved: _PNG})

    out, saved = download_remote_images(md, tmp_path, base_url=base)

    # The `../` climbed past HTML/ to manual/, and the absolute URL was fetched.
    assert client.calls == [resolved]
    assert {p.name for p in saved} == {"topic-fig.png"}
    assert (tmp_path / "images" / "topic-fig.png").read_bytes() == _PNG
    # The original relative ref is retargeted to the local copy.
    assert "](images/topic-fig.png)" in out
    assert "../Storage" not in out


def test_download_relative_ref_untouched_without_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = "![fig](../Storage/pub/fig.png)\n"
    client = _patch_client(monkeypatch, {})  # any fetch would KeyError

    out, saved = download_remote_images(md, tmp_path)

    # No base_url → relative ref left exactly as-is, nothing fetched.
    assert client.calls == []
    assert saved == []
    assert "](../Storage/pub/fig.png)" in out
    assert not (tmp_path / "images").exists()


def test_download_base_url_does_not_rewrite_local_images_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = "![x](images/already-local.png)\n"
    client = _patch_client(monkeypatch, {})

    out, saved = download_remote_images(md, tmp_path, base_url="https://site.com/m/p.html")

    # Our own extracted-asset refs must never be treated as downloadable.
    assert client.calls == []
    assert saved == []
    assert "](images/already-local.png)" in out


def test_download_base_url_skips_relative_non_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = "![doc](../other/page.html)\n![img](../Storage/p.png)\n"
    resolved = "https://site.com/m/Storage/p.png"
    client = _patch_client(monkeypatch, {resolved: _PNG})

    out, saved = download_remote_images(md, tmp_path, base_url="https://site.com/m/HTML/x.html")

    assert client.calls == [resolved]
    assert {p.name for p in saved} == {"Storage-p.png"}
    assert "](../other/page.html)" in out  # non-image relative ref untouched


def test_download_base_url_handles_encoded_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = "![ui](../Storage/topic/1%20main%20ui.png)\n"
    resolved = "https://site.com/m/Storage/topic/1%20main%20ui.png"
    _patch_client(monkeypatch, {resolved: _PNG})

    out, saved = download_remote_images(md, tmp_path, base_url="https://site.com/m/HTML/x.html")

    assert {p.name for p in saved} == {"topic-1%20main%20ui.png"}
    assert "](images/topic-1%20main%20ui.png)" in out


def test_download_base_url_still_handles_absolute_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = "![a](https://docs.x.com/images/eq/a.png)\n![b](../Storage/b.png)\n"
    abs_url = "https://docs.x.com/images/eq/a.png"
    rel_resolved = "https://site.com/m/Storage/b.png"
    _patch_client(monkeypatch, {abs_url: _PNG, rel_resolved: _PNG})

    out, saved = download_remote_images(md, tmp_path, base_url="https://site.com/m/HTML/x.html")

    assert {p.name for p in saved} == {"eq-a.png", "Storage-b.png"}
    assert "](images/eq-a.png)" in out
    assert "](images/Storage-b.png)" in out


# ── config toggles ─────────────────────────────────────────────────────────


def test_enabled_defaults_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGESPEAK_DOWNLOAD_REMOTE_IMAGES", raising=False)
    assert download_remote_images_enabled() is True


def test_enabled_false_when_env_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_DOWNLOAD_REMOTE_IMAGES", "0")
    assert download_remote_images_enabled() is False


def test_timeout_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S", "90")
    assert _remote_image_timeout_s() == 90


def test_timeout_defaults_to_30(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S", raising=False)
    assert _remote_image_timeout_s() == 30


def test_max_bytes_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from pagespeak.backends._remote_images import _remote_image_max_bytes

    monkeypatch.setenv("PAGESPEAK_REMOTE_IMAGE_MAX_BYTES", "1234")
    assert _remote_image_max_bytes() == 1234


def test_download_skips_oversized_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A remote image larger than PAGESPEAK_REMOTE_IMAGE_MAX_BYTES is skipped:
    its ref is kept remote and nothing is written. Bounds an oversized/hostile
    image from filling disk or the downstream vision payload."""
    monkeypatch.setenv("PAGESPEAK_REMOTE_IMAGE_MAX_BYTES", "8")
    url = "https://x.com/images/huge.png"
    md = f"![big]({url})\n"
    _patch_client(monkeypatch, {url: _PNG})  # _PNG is > 8 bytes
    out, saved = download_remote_images(md, tmp_path)
    assert saved == []
    assert f"]({url})" in out
    assert not (tmp_path / "images" / "huge.png").exists()


# ── convert-level integration (HTML path) ──────────────────────────────────


def test_convert_html_downloads_remote_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An HTML doc whose `<img>` tags are remote URLs must, by default, have
    them pulled local + refs retargeted during ingest, so the vision pass can
    later see them."""
    from unittest.mock import patch

    from pagespeak.backends._docx import convert_with_markitdown

    src = tmp_path / "doc.html"
    src.write_text("<html></html>")

    class _R:
        text_content = "# Guide\n\n![fig](https://docs.x.com/images/intro/fig.png)\n"

    _patch_client(monkeypatch, {"https://docs.x.com/images/intro/fig.png": _PNG})
    with patch("markitdown.MarkItDown") as MD:
        MD.return_value.convert.return_value = _R()
        result = convert_with_markitdown(src, output_dir=tmp_path)

    assert {p.name for p in result.images} == {"intro-fig.png"}
    assert (tmp_path / "images" / "intro-fig.png").exists()
    assert "](images/intro-fig.png)" in result.markdown
    assert "https://" not in result.markdown


def test_convert_html_respects_disable_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import patch

    from pagespeak.backends._docx import convert_with_markitdown

    src = tmp_path / "doc.html"
    src.write_text("<html></html>")

    class _R:
        text_content = "![fig](https://docs.x.com/images/intro/fig.png)\n"

    monkeypatch.setenv("PAGESPEAK_DOWNLOAD_REMOTE_IMAGES", "0")
    with patch("markitdown.MarkItDown") as MD:
        MD.return_value.convert.return_value = _R()
        result = convert_with_markitdown(src, output_dir=tmp_path)

    # Disabled: remote ref left as-is, nothing downloaded.
    assert result.images == []
    assert "](https://docs.x.com/images/intro/fig.png)" in result.markdown
    assert not (tmp_path / "images").exists()


def test_convert_html_resolves_relative_refs_with_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`html_base_url` must reach the downloader so a web-help export's
    relative `../Storage/..` refs resolve + download during ingest."""
    from unittest.mock import patch

    from pagespeak.backends._docx import convert_with_markitdown

    src = tmp_path / "doc.html"
    src.write_text("<html></html>")

    class _R:
        text_content = "# Guide\n\n![fig](../Storage/topic/fig.png)\n"

    resolved = "https://site.com/manual/Storage/topic/fig.png"
    _patch_client(monkeypatch, {resolved: _PNG})
    with patch("markitdown.MarkItDown") as MD:
        MD.return_value.convert.return_value = _R()
        result = convert_with_markitdown(
            src,
            output_dir=tmp_path,
            html_base_url="https://site.com/manual/HTML/welcome.html",
        )

    assert {p.name for p in result.images} == {"topic-fig.png"}
    assert "](images/topic-fig.png)" in result.markdown
    assert "../Storage" not in result.markdown


# ── SSRF guard ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "0.0.0.0"],
)
def test_host_is_blocked_rejects_internal_addresses(host: str) -> None:
    from pagespeak.backends._remote_images import _host_is_blocked

    assert _host_is_blocked(host) is True


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1"])
def test_host_is_blocked_allows_public_addresses(host: str) -> None:
    from pagespeak.backends._remote_images import _host_is_blocked

    assert _host_is_blocked(host) is False


def test_host_is_blocked_fails_closed_on_unresolvable(monkeypatch) -> None:
    """A host that won't resolve is blocked (fail closed), not fetched."""
    import socket as _socket

    from pagespeak.backends import _remote_images

    def _boom(*a: object, **k: object) -> None:
        raise _socket.gaierror("nope")

    monkeypatch.setattr(_remote_images.socket, "getaddrinfo", _boom)
    assert _remote_images._host_is_blocked("internal.example") is True


def test_download_skips_ssrf_internal_url(tmp_path: Path) -> None:
    """An image ref pointed at a loopback/metadata IP is never fetched — the
    ref is left as-is and nothing is written (no GET reaches the host)."""
    md = "![x](http://127.0.0.1:8080/secret.png)\n"
    out_md, saved = download_remote_images(md, tmp_path)
    assert saved == []
    assert out_md == md
