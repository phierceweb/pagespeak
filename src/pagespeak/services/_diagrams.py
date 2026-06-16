"""Vision diagram extraction: per-pass orchestration + markdown injection.

The vision backends — the three `analyze(image) -> Diagram` LLM clients, the
`VisionBackend` protocol, the `build_backend` factory, and the response →
`Diagram` parsing — live in `_vision_backends.py`. This module owns the per-pass
orchestration (`gather_diagrams`, concurrency, cache-miss detection) and the
markdown injection (`inject_diagrams`, `enrich_with_diagrams`). The backend
names are re-exported below so the public + test surface is unchanged
(see `_vision_backends.py`).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

from ..models._models import Diagram, IngestResult
from ._vision_backends import (
    CLAUDE_CODE_TIMEOUT_S_DEFAULT as CLAUDE_CODE_TIMEOUT_S_DEFAULT,
)
from ._vision_backends import (
    DEFAULT_VISION_MODEL as DEFAULT_VISION_MODEL,
)
from ._vision_backends import (
    AnthropicVisionBackend as AnthropicVisionBackend,
)
from ._vision_backends import (
    ClaudeCodeVisionBackend as ClaudeCodeVisionBackend,
)
from ._vision_backends import (
    OpenRouterVisionBackend as OpenRouterVisionBackend,
)
from ._vision_backends import (
    VisionBackend as VisionBackend,
)
from ._vision_backends import (
    VisionBackendName as VisionBackendName,
)
from ._vision_backends import (
    _claude_code_timeout_s as _claude_code_timeout_s,
)
from ._vision_backends import (
    _media_type as _media_type,
)
from ._vision_backends import (
    build_backend as build_backend,
)
from ._vision_parse import (
    _build_diagram as _build_diagram,
)
from ._vision_parse import (
    _normalize_parsed as _normalize_parsed,
)
from ._vision_parse import (
    _parse_response as _parse_response,
)

logger = get_logger(__name__)

DEFAULT_VISION_CONCURRENCY = 6
_CONCURRENCY_ENV_VAR = "PAGESPEAK_VISION_CONCURRENCY"


def _resolve_concurrency(concurrency: int | None) -> int:
    """Pick the per-image worker pool size. Explicit arg > env var > default 6.

    Empty / non-numeric env var values fall back to the default with a
    structured `env_var_malformed` warning (via `pf_core.utils.env`) so
    a typo doesn't accidentally serialize the pass. Result is clamped to
    `>= 1` so an explicit `0` / negative arg doesn't deadlock the pool.
    """
    n: int = resolve_int(concurrency, _CONCURRENCY_ENV_VAR, default=DEFAULT_VISION_CONCURRENCY)
    return max(1, n)


_IMAGE_REF = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def alt_text_by_basename(markdown: str) -> dict[str, str]:
    """Map each markdown image ref's basename → its existing alt text.

    Feeds the figure's source description into the alt-text-aware vision
    prompt. First occurrence wins (mirrors `inject_diagrams`'s basename
    matching). The alt is returned verbatim; the prompt renderer trims it.
    """
    out: dict[str, str] = {}
    for m in _IMAGE_REF.finditer(markdown):
        alt, target = m.group(1), m.group(2)
        base = target.rsplit("/", 1)[-1]
        out.setdefault(base, alt)
    return out


# --- Top-level orchestrator (backend-agnostic) ---------------------------


def _process_one_image(
    image_path: Path,
    *,
    backend: VisionBackend,
    backend_name: VisionBackendName,
    model: str | None,
    cache_dir: Path | None,
    cache_only: bool = False,
    original_alt: str = "",
) -> tuple[Diagram, bool, bool, bool]:
    """Phash → cache lookup → backend call (on miss) → cache write.

    Pure per-image work — no shared state, safe to run concurrently across
    a thread pool. Returns `(diagram, was_cache_hit, was_backend_failure,
    was_skipped)` so the orchestrator can keep hits/misses/failures/skipped
    counters without re-doing work.
    """
    # compute phash up front so it's available both for the
    # vision-cache key AND the per-call tracking write. Cheap relative
    # to the LLM call; we want every `llm_runs` row tagged with the
    # phash so calls can be back-referenced to a specific image without
    # an out-of-band lookup.
    cache_path: Path | None = None
    cache_phash: str | None = None
    try:
        from ..utils._phash import compute_phash

        cache_phash = compute_phash(image_path)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("vision_phash_compute_failed path=%s error=%s", image_path, e)
        cache_phash = None

    if cache_dir is not None and cache_phash is not None:
        try:
            from . import _vision_cache as vcache

            cache_path = cache_dir / f"{cache_phash}.json"
            hit = vcache.load(cache_path)
            if hit is not None:
                return vcache.diagram_from_cache(hit, image_path), True, False, False
        except Exception as e:
            # Cache lookup failure is never fatal; fall through to live call.
            logger.warning("vision_cache_lookup_failed path=%s error=%s", image_path, e)
            cache_path = None

    if cache_only:
        # Enforced zero-call mode: a miss is skipped, never sent to the model.
        return (
            Diagram(
                image_path=image_path,
                caption=(
                    f"Image at {image_path.name} (no cached description; "
                    "skipped under --vision-cache-only)."
                ),
                mermaid=None,
            ),
            False,  # not a hit
            False,  # not a failure
            True,  # skipped
        )

    try:
        diagram = backend.analyze(image_path, phash=cache_phash, original_alt=original_alt)
    except Exception as e:
        logger.warning("diagram_extraction_failed path=%s error=%s", image_path, e)
        return (
            Diagram(
                image_path=image_path,
                caption=f"Image at {image_path.name} (extraction failed).",
                mermaid=None,
            ),
            False,
            True,
            False,
        )

    if cache_path is not None:
        try:
            from . import _vision_cache as vcache

            vcache.write(
                cache_path,
                diagram=diagram,
                backend=backend_name,
                model=model,
                phash=cache_phash,
                source_paths=[image_path.name],
            )
        except Exception as e:
            logger.warning("vision_cache_write_failed path=%s error=%s", cache_path, e)

    return diagram, False, False, False


def _any_cache_miss(
    images: list[Path],
    *,
    cache_dir: Path | None,
) -> bool:
    """True if ANY image would require a live backend call — i.e. is not
    already in the per-phash cache.

    When every image is a cache hit, the gather makes ZERO API calls, so
    the auth preflight is pointless. Gating the preflight on this lets a
    fully-cached run succeed with absent/invalid credentials (e.g. reusing
    a prior backend's cache after its key was revoked) instead of failing
    on an auth check it never needed. Cache hits are engine-independent
    (keyed by image phash), so a prior backend's cache satisfies this run.
    Short-circuits on the first miss, so a doc with real work pays at most
    one extra phash.
    """
    if cache_dir is None:
        return True  # no cache → every image is a live call
    from ..utils._phash import compute_phash
    from . import _vision_cache as vcache

    for image_path in images:
        try:
            phash = compute_phash(image_path)
        except Exception:
            return True  # can't phash → can't confirm a hit → treat as work
        if vcache.load(cache_dir / f"{phash}.json") is None:
            return True
    return False


def gather_diagrams(
    images: list[Path],
    *,
    backend: VisionBackend | None = None,
    backend_name: VisionBackendName | None = None,
    model: str | None = None,
    cache_dir: Path | None = None,
    concurrency: int | None = None,
    cache_only: bool = False,
    alt_by_basename: dict[str, str] | None = None,
) -> dict[str, Diagram]:
    """Pure side-file producer for the vision pass. Calls the backend on
    every image (or hits the per-phash cache), writes sidecars, returns
    a `{basename: Diagram}` map. Does NOT mutate any markdown.

    This is the split that makes single-shot match the chunked
    pipeline's gather/assemble model. Pair with `inject_diagrams()` to
    rewrite a markdown stream with the gathered captions + Mermaid
    blocks. The dict is the only handoff between gather and inject —
    safe to compute concurrently with other side-file producers
    (e.g. `gather_normalize_levels()`).

    `cache_dir`, if given, is used as a per-image checkpoint store:
    each successful call writes `<cache_dir>/<phash>.json`, content-keyed
    so the same image rasterized at two paths still hits one entry.
    Cross-backend / cross-model cache invalidation is handled inside
    `_vision_cache.load()`.

    `concurrency` controls the per-image worker pool. None resolves to
    `$PAGESPEAK_VISION_CONCURRENCY` then `DEFAULT_VISION_CONCURRENCY=6`.
    """
    if not images:
        return {}

    # backend_name=None means "consult `PAGESPEAK_VISION_BACKEND`
    # env var via `_agent_runtime.resolve_backend`". The CLI passes None
    # when the user didn't set `--vision-backend` so env wins. Library
    # callers can pass an explicit string to bypass env resolution. We
    # resolve here (before constructing or checking `backend`) so the
    # resolved name is available for cache keying even when a caller
    # injected a pre-built `backend` instance.
    if backend_name is None:
        from .._agent_runtime import resolve_backend as _resolve

        backend_name = _resolve("vision")
    if backend is None:
        backend = build_backend(backend_name, model=model)

    # Pre-flight smoke check. Backends that need it expose
    # `preflight_check()` — currently only `ClaudeCodeVisionBackend`.
    # Other backends rely on the first per-image call surfacing auth
    # issues directly (Anthropic 401, OpenRouter auth error). Duck-typed
    # so test mocks without a preflight method skip silently.
    # Only auth-preflight when there's actual work: a fully-cached pass
    # makes zero API calls and must not fail on a missing/invalid key
    # (e.g. reusing a prior backend's cache). See `_any_cache_miss`.
    preflight = getattr(backend, "preflight_check", None)
    if callable(preflight) and not cache_only and _any_cache_miss(images, cache_dir=cache_dir):
        preflight()

    alt_map = alt_by_basename or {}
    workers = _resolve_concurrency(concurrency)
    total = len(images)
    by_basename: dict[str, Diagram] = {}
    cache_hits = 0
    cache_misses = 0
    backend_failures = 0
    skipped_basenames: list[str] = []

    log_every = max(10, total // 20)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                _process_one_image,
                image_path,
                backend=backend,
                backend_name=backend_name,
                model=model,
                cache_dir=cache_dir,
                cache_only=cache_only,
                original_alt=alt_map.get(image_path.name, ""),
            ): image_path
            for image_path in images
        }
        for completed_count, future in enumerate(as_completed(futures), start=1):
            image_path = futures[future]
            try:
                diagram, hit, failed, skipped = future.result()
            except Exception as e:
                # Belt-and-suspenders: _process_one_image swallows backend
                # failures into a placeholder Diagram, so this only fires
                # on bugs in the per-image worker itself.
                logger.warning("vision_worker_crashed path=%s error=%s", image_path, e)
                diagram = Diagram(
                    image_path=image_path,
                    caption=f"Image at {image_path.name} (extraction failed).",
                    mermaid=None,
                )
                hit = False
                failed = True
                skipped = False
            by_basename[diagram.image_path.name] = diagram
            if skipped:
                skipped_basenames.append(diagram.image_path.name)
            if hit:
                cache_hits += 1
            else:
                cache_misses += 1
            if failed:
                backend_failures += 1
            if completed_count % log_every == 0 or completed_count == total:
                logger.info(
                    "vision_progress completed=%d/%d hits=%d misses=%d failures=%d workers=%d",
                    completed_count,
                    total,
                    cache_hits,
                    cache_misses,
                    backend_failures,
                    workers,
                )

    if cache_only and skipped_basenames:
        logger.warning(
            "vision_cache_only_skipped count=%d images=%s — not in .vision-cache/, "
            "left without a description. Re-run this document WITHOUT "
            "--vision-cache-only to describe them.",
            len(skipped_basenames),
            ", ".join(sorted(skipped_basenames)),
        )

    if cache_dir is not None:
        logger.info(
            "vision_cache_stats hits=%d misses=%d total=%d",
            cache_hits,
            cache_misses,
            cache_hits + cache_misses,
        )

    # End-of-run failure-rate summary. INFO when failures are 0 (so an
    # all-cache-hit run still logs one "0 failures" line), ERROR when the
    # rate is alarming (>= 25%) so a near-total-failure run lights up
    # immediately rather than buried in individual WARNINGs.
    if backend_failures and total:
        rate = backend_failures / total
        emit = logger.error if rate >= 0.25 else logger.warning
        emit(
            "vision_failure_summary failures=%d/%d rate=%.1f%% workers=%d",
            backend_failures,
            total,
            rate * 100,
            workers,
        )
    elif total:
        logger.info(
            "vision_failure_summary failures=0/%d rate=0.0%% workers=%d",
            total,
            workers,
        )

    return by_basename


def inject_diagrams(
    markdown: str, diagrams: dict[str, Diagram], *, preserve_alt: bool = False
) -> str:
    """Pure markdown transform. For each `![...](path)` whose basename
    matches a `Diagram` in `diagrams`, inject a caption (alt text) and
    a Mermaid block (if non-null) below the image ref. Refs without a
    matching diagram are left unchanged.

    Public re-export of the internal `_inject_diagrams` so the
    gather/assemble split has named handles for both halves of the
    vision pass. ``preserve_alt`` (faithful mode) keeps each image's
    existing alt verbatim and only appends Mermaid — see `_inject_diagrams`.
    """
    return _inject_diagrams(markdown, diagrams, preserve_alt=preserve_alt)


def enrich_with_diagrams(
    result: IngestResult,
    *,
    backend: VisionBackend | None = None,
    backend_name: VisionBackendName = "anthropic",
    model: str | None = None,
    cache_dir: Path | None = None,
    concurrency: int | None = None,
) -> IngestResult:
    """Backward-compat wrapper: gather diagrams, inject them into
    `result.markdown`, populate `result.diagrams`. New code should
    prefer the gather + inject pair so vision can run concurrently
    with other side-file producers.
    """
    if not result.images:
        return result

    by_basename = gather_diagrams(
        result.images,
        backend=backend,
        backend_name=backend_name,
        model=model,
        cache_dir=cache_dir,
        concurrency=concurrency,
        alt_by_basename=alt_text_by_basename(result.markdown),
    )
    diagrams = sorted(by_basename.values(), key=lambda d: d.image_path.name)
    result.markdown = inject_diagrams(result.markdown, by_basename)
    result.diagrams = diagrams
    return result


def _escape_alt(text: str) -> str:
    """Make a caption string safe to drop into a markdown image's alt slot.

    Markdown alt text can't contain unescaped `[` or `]` (breaks the syntax)
    or newlines (breaks the image ref). Replace defensively.
    """
    return text.replace("[", "(").replace("]", ")").replace("\n", " ").strip()


def _inject_diagrams(
    markdown: str, diagrams: dict[str, Diagram], *, preserve_alt: bool = False
) -> str:
    """Rewrite each `![...](path)` whose basename matches a `Diagram`:

    - Caption goes into the image's alt text (structurally extractable).
    - Mermaid block (if any) is appended below, tagged with
      `pagespeak-image="<path>"` in the fenced-block info string so
      consumers can pair the Mermaid with its source image.

    Refs whose basename has no matching `Diagram` are left unchanged.

    With ``preserve_alt`` (faithful mode), the image's existing alt is kept
    **verbatim** — the enriched caption is NOT injected — and only the Mermaid
    block is appended (for diagrams). A non-diagram figure is left untouched.
    Use this to add structure without modifying a publisher's source alt text.
    """

    def repl(match: re.Match[str]) -> str:
        path = match.group(2)
        basename = path.rsplit("/", 1)[-1]
        diagram = diagrams.get(basename)
        if not diagram:
            return match.group(0)
        # Faithful mode keeps the source alt verbatim (match.group(0)) and only
        # appends Mermaid; otherwise the enriched caption replaces the alt.
        ref = match.group(0) if preserve_alt else f"![{_escape_alt(diagram.caption)}]({path})"
        if diagram.mermaid:
            return f'{ref}\n\n```mermaid pagespeak-image="{path}"\n{diagram.mermaid}\n```'
        return ref

    return _IMAGE_REF.sub(repl, markdown)
