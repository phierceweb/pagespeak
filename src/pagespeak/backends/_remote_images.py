"""Download remote image refs in HTML-derived markdown to local files.

MarkItDown converts an HTML document by preserving its ``<img src="http…">``
tags as remote markdown image refs — it never downloads the binaries. The
pagespeak vision pass only processes images that live locally under
``<output_dir>/images/``, so a converted HTML doc's figures would be invisible
to vision. This module closes that gap over ``pf_core.fetch.images``, which
owns the download / naming / retarget mechanics (and the SSRF guard); what
lives here is the pagespeak-side policy: the ``PAGESPEAK_*`` operator knobs and
the pipeline entry points. Mirrors what ``_docx._extract_epub_media`` +
``_retarget_image_refs`` do for EPUB.

Runs in the ingest step, so the emitted ``<stem>.raw.md`` already carries
local paths and every downstream phase inherits them. On by default for HTML
ingest; gated by ``PAGESPEAK_DOWNLOAD_REMOTE_IMAGES``. A file already on disk
(same dest) is reused, not re-fetched; a failed download keeps its remote URL
so the ref still resolves in a browser.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Protocol

from pf_core.fetch import Fetcher
from pf_core.fetch.images import default_namer, localize_images
from pf_core.log import get_logger
from pf_core.utils.env import resolve_bool, resolve_int

logger = get_logger(__name__)

DOWNLOAD_REMOTE_IMAGES_ENV_VAR = "PAGESPEAK_DOWNLOAD_REMOTE_IMAGES"
DEFAULT_DOWNLOAD_REMOTE_IMAGES = True

REMOTE_IMAGE_TIMEOUT_ENV_VAR = "PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S"
DEFAULT_REMOTE_IMAGE_TIMEOUT_S = 30

REMOTE_IMAGE_MAX_BYTES_ENV_VAR = "PAGESPEAK_REMOTE_IMAGE_MAX_BYTES"
DEFAULT_REMOTE_IMAGE_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB

# The on-disk naming scheme; `_local_images._flat_name` mirrors it for local refs.
_local_name = default_namer


class _BytesFetcher(Protocol):
    def get_bytes(self, url: str, *, timeout_s: float = ...) -> tuple[str, bytes]: ...


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


def _make_fetcher() -> _BytesFetcher:
    """Size-capped fetcher for one localize pass; the cap is re-read per call."""
    return Fetcher(max_bytes=_remote_image_max_bytes())


class _TimeoutPinnedFetcher:
    """Fetcher adapter that pins every request to the operator's timeout."""

    def __init__(self, fetcher: _BytesFetcher, timeout_s: float) -> None:
        self._fetcher = fetcher
        self._timeout_s = timeout_s

    def get_bytes(self, url: str, *, timeout_s: float | None = None) -> tuple[str, bytes]:
        """Discards the localizer's own ``timeout_s`` so
        ``PAGESPEAK_REMOTE_IMAGE_TIMEOUT_S`` wins."""
        return self._fetcher.get_bytes(url, timeout_s=self._timeout_s)


def download_remote_images(
    markdown: str, output_dir: Path, *, base_url: str | None = None
) -> tuple[str, list[Path]]:
    """Download remote/relative image refs to ``output_dir/images/``; retarget local.

    Returns ``(rewritten_markdown, saved_paths)``. ``http(s)://`` image refs
    are always downloaded. When ``base_url`` is given, relative refs
    (``../Storage/foo.png`` — typical of HTML web-help exports) are resolved
    against it and downloaded too; without it they're left untouched for the
    browser. Non-image refs, refs blocked by the SSRF guard, and refs whose
    download fails keep their original target. A ref whose local file already
    exists is reused without re-fetching. Nothing is fetched and no ``images/``
    dir is created when there is nothing to download. Each saved file is listed
    once; distinct URLs that land on one name log ``remote_image_name_collision``.
    """
    urls_by_name: defaultdict[str, set[str]] = defaultdict(set)

    def namer(url: str) -> str:
        name = _local_name(url)
        urls_by_name[name].add(url)
        return name

    result = localize_images(
        markdown,
        output_dir / "images",
        base_url=base_url,
        fetcher=_TimeoutPinnedFetcher(_make_fetcher(), _remote_image_timeout_s()),
        namer=namer,
        reuse_existing=True,
    )
    for name, urls in urls_by_name.items():
        if len(urls) > 1:
            # The later URLs reuse the first one's file, so they show its image.
            logger.warning("remote_image_name_collision name=%s urls=%d", name, len(urls))
    return result.markdown, list(dict.fromkeys(result.saved))


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
