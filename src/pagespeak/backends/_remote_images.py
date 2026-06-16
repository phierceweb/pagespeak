"""Download remote image refs in HTML-derived markdown to local files.

MarkItDown converts an HTML document by preserving its ``<img src="http…">``
tags as remote markdown image refs — it never downloads the binaries. The
pagespeak vision pass only processes images that live locally under
``<output_dir>/images/``, so a converted HTML doc's figures would be invisible
to vision. This module closes that gap: it downloads every remote image ref
into ``images/<name>`` and rewrites the ref to the local path, mirroring what
``_docx._extract_epub_media`` + ``_retarget_image_refs`` do for EPUB.

Runs in the ingest step, so the emitted ``<stem>.raw.md`` already carries
local paths and every downstream phase inherits them. On by default for HTML
ingest; gated by ``PAGESPEAK_DOWNLOAD_REMOTE_IMAGES``. A file already on disk
(same dest) is reused, not re-fetched; a failed download keeps its remote URL
so the ref still resolves in a browser.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pf_core.log import get_logger
from pf_core.utils.env import resolve_bool, resolve_int

logger = get_logger(__name__)

DOWNLOAD_REMOTE_IMAGES_ENV_VAR = "PAGESPEAK_DOWNLOAD_REMOTE_IMAGES"
DEFAULT_DOWNLOAD_REMOTE_IMAGES = True

REMOTE_IMAGE_TIMEOUT_ENV_VAR = "PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S"
DEFAULT_REMOTE_IMAGE_TIMEOUT_S = 30

REMOTE_IMAGE_MAX_BYTES_ENV_VAR = "PAGESPEAK_REMOTE_IMAGE_MAX_BYTES"
DEFAULT_REMOTE_IMAGE_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

# Remote image refs only: `![alt](http(s)://…)`. Local refs (no scheme) and
# other schemes (data:, file:) are left for other passes / the browser.
_REMOTE_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")

# Relative image refs (no scheme): `![alt](../Storage/foo.png)`. Resolved
# against a caller-supplied base URL ONLY (web-help exports reference assets
# by relative path, not URL). Excludes our own
# extracted `images/` dir, absolute filesystem paths, and `data:`/scheme'd
# refs so they're never mistaken for downloadable relative paths.
_RELATIVE_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\((?!https?://|images/|/|data:)([^)\s]+)\)")


def _host_is_blocked(host: str) -> bool:
    """True if ``host`` resolves to any private / loopback / link-local /
    reserved address — the SSRF guard. An unresolvable host is blocked too
    (fail closed).

    pagespeak converts documents it did not author, so a malicious doc must
    never be able to point the downloader at internal services (cloud metadata
    endpoints, ``localhost``, the private network).
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def _url_is_blocked(url: str) -> bool:
    host = urlparse(url).hostname
    return _host_is_blocked(host) if host else True


def _safe_get(client: httpx.Client, url: str, *, max_redirects: int = 5) -> httpx.Response:
    """GET ``url`` with an SSRF host check on every hop. Redirects are followed
    manually so a public URL can't 30x-bounce to an internal address. Raises
    ``httpx.RequestError`` on a blocked host or a redirect loop."""
    for _ in range(max_redirects + 1):
        if _url_is_blocked(url):
            raise httpx.RequestError(f"blocked host (SSRF guard): {url}")
        resp = client.get(url)
        if resp.is_redirect:
            loc = resp.headers.get("location")
            if not loc:
                return resp
            url = urljoin(url, loc)
            continue
        return resp
    raise httpx.RequestError(f"too many redirects: {url}")


def download_remote_images_enabled() -> bool:
    """Whether HTML ingest downloads remote images (default on).

    Operational toggle (env-configurable) —
    ``PAGESPEAK_DOWNLOAD_REMOTE_IMAGES=0`` disables it (leave remote refs as
    external URLs; the vision pass then can't see HTML figures). Read at call
    time so a long-lived process picks up ``.env`` changes between docs.
    """
    return bool(
        resolve_bool(None, DOWNLOAD_REMOTE_IMAGES_ENV_VAR, default=DEFAULT_DOWNLOAD_REMOTE_IMAGES)
    )


def _remote_image_timeout_s() -> int:
    """Per-request download timeout (s); ``PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S``."""
    return int(
        resolve_int(None, REMOTE_IMAGE_TIMEOUT_ENV_VAR, default=DEFAULT_REMOTE_IMAGE_TIMEOUT_S)
    )


def _remote_image_max_bytes() -> int:
    """Max bytes for one downloaded remote image (over it → skipped, ref kept
    remote); ``PAGESPEAK_REMOTE_IMAGE_MAX_BYTES`` (default 25 MiB)."""
    return int(
        resolve_int(None, REMOTE_IMAGE_MAX_BYTES_ENV_VAR, default=DEFAULT_REMOTE_IMAGE_MAX_BYTES)
    )


def _local_name(url: str) -> str:
    """Derive a collision-resistant local filename from a remote URL.

    Joins the path segments after the first ``images`` component with dashes
    (``…/images/getting-started/foo.png`` → ``getting-started-foo.png``) so
    two figures sharing a basename in different sub-paths don't collide.
    Falls back to the last two path components when there's no ``images``
    segment.
    """
    path = urlparse(url).path
    parts = Path(path).parts
    try:
        idx = next(i for i, p in enumerate(parts) if p == "images")
        sub = parts[idx + 1 :]
    except StopIteration:
        sub = parts[-2:] if len(parts) >= 2 else parts
    name = "-".join(sub) if sub else Path(path).name
    return name.replace("/", "-")


def _is_image_url(url: str) -> bool:
    """Whether a markdown image ref's URL should be downloaded.

    The ref already came from ``![...](...)`` (image syntax), so an image
    extension OR no extension at all both qualify — the latter covers opaque
    CDN URLs like some help sites (``/assets/v2/web/<uuid>``). Only a
    *non-image* extension (``.html`` / ``.css`` / …) is rejected.
    """
    suffix = Path(urlparse(url).path.rstrip("/")).suffix.lower()
    return suffix == "" or suffix in _IMAGE_EXTENSIONS


def _ext_from_bytes(data: bytes) -> str:
    """Best-effort image extension from magic bytes, for extensionless URLs."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return ".svg"
    return ".png"  # default: PNG is the most common web figure format


def _existing_local(images_dir: Path, base: str, has_ext: bool) -> Path | None:
    """Already-downloaded local file for ``base``, if any (reuse, don't refetch).

    For an extensionless base, the sniffed extension was appended on the first
    run, so probe each known image extension rather than the bare name.
    """
    if has_ext:
        p = images_dir / base
        return p if p.exists() else None
    for ext in _IMAGE_EXTENSIONS:
        p = images_dir / f"{base}{ext}"
        if p.exists():
            return p
    return None


def _download_targets(markdown: str, base_url: str | None) -> list[tuple[str, str]]:
    """Build ``(ref_string, fetch_url)`` pairs to download, in stable order.

    ``ref_string`` is the literal text inside ``](…)`` (used to retarget the
    ref); ``fetch_url`` is what we GET. For ``http(s)://`` refs the two are
    identical; for relative refs (only when ``base_url`` is set) the fetch URL
    is ``urljoin(base_url, ref)``. Non-image refs and duplicates are dropped.
    """
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _REMOTE_IMG_REF_RE.finditer(markdown):
        url = m.group(1)
        if _is_image_url(url) and url not in seen:
            seen.add(url)
            targets.append((url, url))
    if base_url:
        for m in _RELATIVE_IMG_REF_RE.finditer(markdown):
            ref = m.group(1)
            if _is_image_url(ref) and ref not in seen:
                seen.add(ref)
                targets.append((ref, urljoin(base_url, ref)))
    return targets


def download_remote_images(
    markdown: str, output_dir: Path, *, base_url: str | None = None
) -> tuple[str, list[Path]]:
    """Download remote/relative image refs to ``output_dir/images/``; retarget local.

    Returns ``(rewritten_markdown, saved_paths)``. ``http(s)://`` image refs
    are always downloaded. When ``base_url`` is given, relative refs
    (``../Storage/foo.png`` — typical of HTML web-help exports) are resolved
    against it and downloaded too; without it they're left untouched for the
    browser. Non-image refs and refs whose download fails keep their original
    target. A ref whose local file already exists is reused without
    re-fetching. No-op (no HTTP client opened) when there's nothing to fetch.
    """
    targets = _download_targets(markdown, base_url)
    if not targets:
        return markdown, []

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    ref_to_local: dict[str, str] = {}
    saved: list[Path] = []
    failed = 0
    max_bytes = _remote_image_max_bytes()
    with httpx.Client(follow_redirects=False, timeout=_remote_image_timeout_s()) as client:
        for ref, fetch_url in targets:
            base = _local_name(fetch_url)
            has_ext = Path(base).suffix.lower() in _IMAGE_EXTENSIONS
            existing = _existing_local(images_dir, base, has_ext)
            if existing is not None:
                ref_to_local[ref] = f"images/{existing.name}"
                saved.append(existing)
                continue
            try:
                resp = _safe_get(client, fetch_url)
                resp.raise_for_status()
                data = resp.content
                if len(data) > max_bytes:
                    failed += 1
                    logger.warning("remote_image_too_large url=%s bytes=%d", fetch_url, len(data))
                    continue
                # Extensionless CDN URL: sniff a real extension from the bytes
                # so the ref + downstream vision media-type are correct.
                name = base if has_ext else base + _ext_from_bytes(data)
                dest = images_dir / name
                dest.write_bytes(data)
            except (httpx.HTTPError, OSError) as e:
                # Network / HTTP-status / disk error: keep the original ref so
                # it still resolves in a browser; log and carry on.
                failed += 1
                logger.warning("remote_image_download_failed url=%s error=%s", fetch_url, e)
                continue
            ref_to_local[ref] = f"images/{dest.name}"
            saved.append(dest)

    rewritten = markdown
    for ref, local in ref_to_local.items():
        rewritten = rewritten.replace(f"]({ref})", f"]({local})")

    logger.debug(
        "remote_images_downloaded ok=%d failed=%d total=%d",
        len(saved),
        failed,
        len(targets),
    )
    return rewritten, saved


def localize_remote_images_in_markdown(
    markdown: str, output_dir: Path, *, images: list[Path] | None = None
) -> tuple[str, list[Path]]:
    """Cleanup-phase entry point: localize a markdown/dir-mode source's remote
    image refs and merge the new local files into ``images``.

    The HTML/ingest path already downloads images in ``IngestPhase``; a
    markdown/dir-mode source skipped ingest, so its refs are still remote at
    cleanup. Returns ``(rewritten_markdown, images)`` — a no-op (inputs
    unchanged) when the toggle is off (``PAGESPEAK_DOWNLOAD_REMOTE_IMAGES``) or
    there is nothing remote to fetch (e.g. an HTML doc whose refs are already
    local). Markdown sources are expected to carry absolute/resolvable URLs.
    """
    base = list(images or [])
    if not download_remote_images_enabled():
        return markdown, base
    rewritten, saved = download_remote_images(markdown, output_dir)
    if not saved:
        return markdown, base
    seen = {str(p) for p in base}
    return rewritten, base + [p for p in saved if str(p) not in seen]
