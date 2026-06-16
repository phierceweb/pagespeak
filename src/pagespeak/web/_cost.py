"""Cost-safety pre-flight for vision runs.

Encodes the cost-safety + caching rules:
vision defaults to ``claude_code`` ($0); any live vision call needs an
explicit confirm; a *paid* backend with an unknown image count is blocked
(no ungrounded estimate). Cache misses are computed per-image by phash, the
same key the pipeline uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pagespeak.utils._phash import compute_phash

_PHASE_ORDER = {
    "ingest": 0,
    "cleanup": 1,
    "normalize": 2,
    "repair": 3,
    "structure": 4,
    "vision": 5,
    "split": 6,
}
_VISION_IDX = _PHASE_ORDER["vision"]
_LAST_IDX = max(_PHASE_ORDER.values())
_PAID_BACKENDS = {"anthropic", "openrouter"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}


def vision_will_run(
    start: str | None, stop_after: str | None, *, diagrams: bool, cache_only: bool
) -> bool:
    """True if the phase slice will make live vision calls."""
    if not diagrams or cache_only:
        return False
    lo = _PHASE_ORDER.get(start, 0) if start else 0
    hi = _PHASE_ORDER.get(stop_after, _LAST_IDX) if stop_after else _LAST_IDX
    return lo <= _VISION_IDX <= hi


def cache_miss_count(out_dir: Path) -> tuple[int, int, int] | None:
    """Return ``(images, cached, misses)`` or ``None`` if no images extracted yet.

    A miss is an image whose perceptual hash has no ``.vision-cache/<phash>.json``.
    """
    images_dir = out_dir / "images"
    if not images_dir.is_dir():
        return None
    images = [f for f in images_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTS]
    if not images:
        return None
    cache_dir = out_dir / ".vision-cache"
    cached = 0
    for img in images:
        phash = _safe_phash(img)
        if phash and (cache_dir / f"{phash}.json").is_file():
            cached += 1
    return (len(images), cached, len(images) - cached)


def _safe_phash(img: Path) -> str | None:
    """Perceptual hash of ``img``, or ``None`` if it can't be read.

    ``compute_phash`` raises on an unreadable/non-image file. An image
    whose hash can't be computed has no cache entry by definition, so it
    counts as a *miss* — the conservative (more-confirm, never-underestimate)
    direction the cost gate wants. A bad image must never 500 the gate.
    """
    try:
        # compute_phash is typed Any to mypy (pf_core is untyped here); bind to
        # a str-annotated local so the return doesn't trip no-any-return.
        phash: str = compute_phash(img)
        return phash
    except Exception:
        return None


@dataclass(frozen=True)
class GateDecision:
    needs_confirm: bool
    blocked: bool
    message: str = ""
    images: int | None = None
    cached: int | None = None
    misses: int | None = None
    backend: str = "claude_code"


def gate_decision(
    *, out_dir: Path | None, will_run: bool, backend: str, confirmed: bool
) -> GateDecision:
    """Decide whether a submit needs a confirm card, is blocked, or proceeds."""
    if not will_run:
        return GateDecision(needs_confirm=False, blocked=False)

    counts = cache_miss_count(out_dir) if out_dir is not None else None
    is_paid = backend in _PAID_BACKENDS

    if counts is None:
        if is_paid:
            return GateDecision(
                needs_confirm=False,
                blocked=True,
                backend=backend,
                message=(
                    "Image count unknown until ingest runs — a paid backend can't "
                    "be cost-estimated. Run ingest first, or use claude_code / cache-only."
                ),
            )
        if confirmed:
            return GateDecision(needs_confirm=False, blocked=False, backend=backend)
        return GateDecision(
            needs_confirm=True,
            blocked=False,
            backend=backend,
            message=(
                "Vision will run on claude_code: one Max-quota call per uncached image "
                "($0). Exact count known after ingest. Confirm to proceed."
            ),
        )

    images, cached, misses = counts
    if confirmed:
        return GateDecision(
            needs_confirm=False,
            blocked=False,
            backend=backend,
            images=images,
            cached=cached,
            misses=misses,
        )
    if is_paid:
        est = _estimate_paid(misses)
        money = f" ≈ ${est:.2f}" if est is not None else ""
        msg = (
            f"{images} images · {cached} cached · {misses} live calls on {backend}{money}. "
            f"Paid backend — confirm to spend."
        )
    else:
        msg = (
            f"{images} images · {cached} cached · {misses} live calls on claude_code "
            f"→ {misses} Max-quota calls ($0). Confirm to proceed."
        )
    return GateDecision(
        needs_confirm=True,
        blocked=False,
        backend=backend,
        images=images,
        cached=cached,
        misses=misses,
        message=msg,
    )


def _estimate_paid(misses: int) -> float | None:
    """Rough $ estimate for ``misses`` paid vision calls (~4K in / ~1K out per image)."""
    try:
        from pf_core.budget import project_cost

        per: float = project_cost(
            agent_type="vision",
            model="claude-haiku-4-5-20251001",
            estimated_prompt_tokens=4000,
            estimated_completion_tokens=1000,
        )
        return per * misses
    except Exception:
        return None
