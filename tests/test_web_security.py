"""Tests for pagespeak.web._security — the console's request guards and headers."""

from __future__ import annotations

import pf_core.db.connection as conn_mod
import pytest
from fastapi.testclient import TestClient

from pagespeak.web import create_app
from pagespeak.web._security import (
    allowed_hosts,
    bind_is_exposed,
    content_security_policy,
    is_cross_site,
)

HOST = "127.0.0.1:8810"


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        ("GET", {"sec-fetch-site": "cross-site"}, False),
        ("POST", {"sec-fetch-site": "same-origin"}, False),
        ("POST", {"sec-fetch-site": "none"}, False),
        ("POST", {"sec-fetch-site": "cross-site"}, True),
        ("POST", {"sec-fetch-site": "same-site"}, True),
        ("POST", {"origin": f"http://{HOST}"}, False),
        ("POST", {"origin": "https://evil.example"}, True),
        ("POST", {"origin": "null"}, True),
        ("POST", {}, False),
    ],
)
def test_is_cross_site(method: str, headers: dict[str, str], expected: bool) -> None:
    assert is_cross_site(method, headers, HOST) is expected


def test_allowed_hosts_are_loopback_plus_the_bind_host_plus_extras(monkeypatch) -> None:
    monkeypatch.setenv("PAGESPEAK_WEB_ALLOWED_HOSTS", "console.lan, 10.0.0.5")
    assert allowed_hosts("0.0.0.0") == {"127.0.0.1", "localhost", "::1", "console.lan", "10.0.0.5"}
    monkeypatch.delenv("PAGESPEAK_WEB_ALLOWED_HOSTS")
    assert "192.168.1.9" in allowed_hosts("192.168.1.9")


def test_csp_carries_the_nonce_and_forbids_inline_handlers() -> None:
    csp = content_security_policy("abc123")
    assert "script-src 'self' 'nonce-abc123'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp


def _client(monkeypatch, tmp_path, **env: str) -> TestClient:
    conv = tmp_path / "conversions"
    (conv / "in").mkdir(parents=True)
    (conv / "out").mkdir(parents=True)
    (conv / "in" / "Doc.pdf").write_text("x", encoding="utf-8")
    monkeypatch.setenv("PAGESPEAK_CONVERSIONS_DIR", str(conv))
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    conn_mod.reset_engine()
    import pagespeak._db as db

    db._initialized = False
    return TestClient(create_app(start_worker=False))


def test_cross_site_post_is_refused_before_it_queues_a_run(monkeypatch, tmp_path) -> None:
    """A hostile page can make the browser POST to the console; `confirmed=1`
    would otherwise pass the cost gate and spend quota."""
    client = _client(monkeypatch, tmp_path)
    r = client.post(
        "/api/run/doc",
        data={"diagrams": "true", "confirmed": "1"},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert "doc" not in client.get("/partials/queue").text.lower()


def test_same_origin_post_still_works(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    r = client.post(
        "/api/run/doc",
        data={"diagrams": "false"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert r.status_code != 403


def test_an_unlisted_host_is_refused(monkeypatch, tmp_path) -> None:
    """DNS rebinding: a hostile domain resolved to 127.0.0.1 looks same-origin to
    the browser, so only the Host header gives it away."""
    client = _client(monkeypatch, tmp_path)
    assert client.get("/", headers={"Host": "evil.example:8810"}).status_code == 403
    assert client.get("/", headers={"Host": "localhost:8810"}).status_code == 200


def test_every_page_gets_a_csp_with_a_fresh_nonce_the_page_uses(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    out = tmp_path / "conversions" / "out" / "doc"
    out.mkdir()
    (out / "Doc.raw.md").write_text("# raw", encoding="utf-8")

    first = client.get("/c/doc")
    second = client.get("/c/doc")
    nonce = first.headers["content-security-policy"].split("'nonce-", 1)[1].split("'", 1)[0]
    assert nonce not in second.headers["content-security-policy"]
    assert f'nonce="{nonce}"' in first.text
    assert "<script>" not in first.text  # every inline script carries the nonce
    assert first.headers["x-content-type-options"] == "nosniff"


def test_an_oversized_request_is_refused_before_it_is_read(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path, PAGESPEAK_WEB_MAX_UPLOAD_BYTES="100")
    r = client.post("/api/upload", files={"file": ("big.pdf", b"x" * 1000)})
    assert r.status_code == 413
    assert not (tmp_path / "conversions" / "in" / "big.pdf").exists()


def test_fragments_carry_no_inline_script(monkeypatch, tmp_path) -> None:
    """htmx re-creates scripts in swapped fragments; an inline one would need the
    page's nonce, and so would any script injected into a fragment."""
    client = _client(monkeypatch, tmp_path)
    r = client.get("/partials/actions/doc")
    assert '<script src="/static/actions.js"></script>' in r.text
    assert "<script>" not in r.text and "nonce=" not in r.text
    assert client.get("/static/actions.js").status_code == 200


def test_inline_html_responses_escape_their_text(monkeypatch, tmp_path) -> None:
    import pagespeak.services._deliver as deliver_mod

    client = _client(monkeypatch, tmp_path)
    out = tmp_path / "conversions" / "out" / "doc"
    out.mkdir()
    (out / "Doc.md").write_text("# doc", encoding="utf-8")

    def boom(*_a, **_k):
        raise ValueError("<img src=x onerror=alert(1)>")

    monkeypatch.setattr(deliver_mod, "strip_for_delivery", boom)
    r = client.post("/api/deliver/doc")
    assert "&lt;img src=x onerror=alert(1)&gt;" in r.text
    assert "<img src=x" not in r.text


@pytest.mark.parametrize(
    ("host", "exposed"),
    [
        ("127.0.0.1", False),
        ("localhost", False),
        ("::1", False),
        ("0.0.0.0", True),
        ("192.168.1.9", True),
    ],
)
def test_bind_is_exposed(host: str, exposed: bool) -> None:
    assert bind_is_exposed(host) is exposed


def test_allowed_hosts_match_whatever_the_case(monkeypatch, tmp_path) -> None:
    """Host names are case-insensitive and the request's Host is lowercased, so a
    listed name written with capitals refused every request."""
    client = _client(monkeypatch, tmp_path, PAGESPEAK_WEB_ALLOWED_HOSTS="MyMac.local")
    assert client.get("/", headers={"Host": "MyMac.local:8810"}).status_code == 200
    assert "console.lan" in allowed_hosts("Console.LAN")


def test_a_body_without_a_length_is_capped_while_it_arrives(monkeypatch, tmp_path) -> None:
    """A chunked request has no Content-Length to refuse up front; without a cap
    on the stream the whole body is spooled to disk before the handler runs.
    Driven through ASGI directly: TestClient hands the app the body in one piece."""
    import asyncio

    client = _client(monkeypatch, tmp_path, PAGESPEAK_WEB_MAX_UPLOAD_BYTES="1000")
    boundary = "pagespeak-test-boundary"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    pieces = [head, *([b"x" * 1024] * 64), f"\r\n--{boundary}--\r\n".encode()]
    pulled: list[int] = []
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        if len(pulled) == len(pieces):
            return {"type": "http.disconnect"}
        pulled.append(len(pieces[len(pulled)]))
        return {"type": "http.request", "body": pieces[len(pulled) - 1], "more_body": True}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/upload",
        "raw_path": b"/api/upload",
        "root_path": "",
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"transfer-encoding", b"chunked"),
        ],
    }
    asyncio.run(client.app(scope, receive, send))

    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [413]
    assert sum(pulled) < 2000
    assert not (tmp_path / "conversions" / "in" / "big.pdf").exists()
