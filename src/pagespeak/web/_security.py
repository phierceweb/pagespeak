"""Request guards and security headers for the console.

The console has no auth and binds to loopback, which stops remote access but
not the browser on this machine being turned against it:

- **DNS rebinding** — a hostile domain re-resolved to 127.0.0.1 is same-origin
  to the browser; only its Host header gives it away. Hosts outside the
  allowlist are refused.
- **Cross-site writes** — a page on another site can submit a form here, and a
  queued run spends quota or money. A write the browser marks as cross-site
  (`Sec-Fetch-Site`, or an `Origin` other than the host) is refused.
- **Oversized bodies** — refused from `Content-Length` before they are read.
- **Document content in the preview** — converted markdown can carry hostile
  HTML. A nonce-based Content-Security-Policy stops its script handlers,
  `javascript:` links, frames and plugins. Page scripts carry the nonce;
  HTMX fragments load theirs from `/static`, so a fragment never needs it.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Mapping
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pf_core.utils.env import resolve_int, resolve_str
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_UPLOAD_BYTES_DEFAULT = 512 * 1024 * 1024
_MAX_UPLOAD_BYTES_ENV_VAR = "PAGESPEAK_WEB_MAX_UPLOAD_BYTES"
_ALLOWED_HOSTS_ENV_VAR = "PAGESPEAK_WEB_ALLOWED_HOSTS"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_WILDCARD_BINDS = frozenset({"0.0.0.0", "::", ""})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAME_SITE_FETCH = frozenset({"same-origin", "none"})
# The CDNs the console's pages load their scripts and styles from.
_CDN_SCRIPTS = "https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net"


def max_upload_bytes() -> int:
    value: int = resolve_int(None, _MAX_UPLOAD_BYTES_ENV_VAR, default=MAX_UPLOAD_BYTES_DEFAULT)
    return value


def bind_is_exposed(bind_host: str) -> bool:
    """True when the console would be reachable from other machines."""
    return bind_host not in _LOOPBACK_HOSTS


def allowed_hosts(bind_host: str) -> set[str]:
    """Loopback names, the bind host when it names one, and `PAGESPEAK_WEB_ALLOWED_HOSTS`,
    lowercased like the request's Host before the lookup."""
    hosts = set(_LOOPBACK_HOSTS)
    if bind_host not in _WILDCARD_BINDS:
        hosts.add(bind_host.strip("[]").lower())
    extra = resolve_str(None, _ALLOWED_HOSTS_ENV_VAR, default="") or ""
    hosts.update(h.strip().lower() for h in extra.split(",") if h.strip())
    return hosts


def _hostname(host_header: str) -> str:
    return (urlsplit(f"//{host_header}").hostname or "").lower()


def is_cross_site(method: str, headers: Mapping[str, str], host: str) -> bool:
    """True when a browser says this write came from another origin.

    A request with neither header is not from a browser page (curl, scripts)
    and carries no cross-site risk.
    """
    if method.upper() in _SAFE_METHODS:
        return False
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in _SAME_SITE_FETCH
    origin = headers.get("origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc != host


def content_security_policy(nonce: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' {_CDN_SCRIPTS}",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            "img-src 'self' data: blob:",
            "font-src 'self' data: https://cdn.jsdelivr.net",
            "connect-src 'self' https://cdn.jsdelivr.net",
            "object-src 'none'",
            "frame-src 'none'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        )
    )


def _refusal(request: Request, hosts: set[str]) -> Response | None:
    host_header = request.headers.get("host", "")
    if _hostname(host_header) not in hosts:
        return PlainTextResponse("host not allowed", status_code=403)
    if is_cross_site(request.method, request.headers, host_header):
        return PlainTextResponse("cross-site request refused", status_code=403)
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > max_upload_bytes():
        return PlainTextResponse("request body too large", status_code=413)
    return None


class BodyLimit:
    """Counts a request body as it arrives: a chunked upload has no Content-Length
    to refuse up front, and the form parser would spool all of it to disk."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = max_upload_bytes()
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(status_code=413, detail="request body too large")
            return message

        await self.app(scope, counted, send)


def install_security(app: FastAPI, *, bind_host: str) -> None:
    hosts = allowed_hosts(bind_host)
    # Innermost, so the route reads through it directly: raised under an outer
    # BaseHTTPMiddleware's task group, the 413 arrives as an ExceptionGroup → 400.
    app.user_middleware.append(Middleware(BodyLimit))

    @app.middleware("http")
    async def _guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        refused = _refusal(request, hosts)
        if refused is not None:
            return refused
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # pf-core's admin pages ship their own inline scripts.
        if not request.url.path.startswith("/admin"):
            response.headers["Content-Security-Policy"] = content_security_policy(nonce)
        return response
