"""Copy local sibling image refs into the output dir.

An HTML bundle (saved webpage, doc-site export) ships ``doc.html`` plus a
sibling ``images/`` dir with relative refs. MarkItDown keeps the refs but
nothing copies the files, so the vision pass — which only globs
``<output_dir>/images/`` — sees nothing. This closes the local half of the gap
``_remote_images`` closes for URLs: refs pointing at files already on disk
next to the source, just not in the output dir.

Runs in ingest (HTML/markdown sources) and cleanup (dir-mode/markdown resume);
gated by ``PAGESPEAK_COPY_LOCAL_IMAGES`` (default on).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pf_core.log import get_logger
from pf_core.utils.env import resolve_bool

from ..services._image_refs import ImageRef, replace_image_refs

logger = get_logger(__name__)

COPY_LOCAL_IMAGES_ENV_VAR = "PAGESPEAK_COPY_LOCAL_IMAGES"
DEFAULT_COPY_LOCAL_IMAGES = True

_EXTERNAL_PREFIXES = ("http://", "https://", "/", "data:", "file:")


def copy_local_images_enabled() -> bool:
    """Whether sibling-image localization runs (default on).

    Operational toggle — ``PAGESPEAK_COPY_LOCAL_IMAGES=0`` leaves refs
    pointing at the source tree. Read at call time so a long-lived process
    picks up ``.env`` changes between docs.
    """
    return bool(resolve_bool(None, COPY_LOCAL_IMAGES_ENV_VAR, default=DEFAULT_COPY_LOCAL_IMAGES))


def _is_local(dest: str) -> bool:
    return bool(dest) and not dest.startswith(_EXTERNAL_PREFIXES)


def _flat_name(rel: Path) -> str:
    """Collision-resistant flat filename for a non-canonical ref (mirrors
    `_remote_images._local_name`): the parts after an ``images`` component,
    else the last two, dash-joined. Flat because the vision glob is
    non-recursive."""
    parts = rel.parts
    try:
        idx = next(i for i, p in enumerate(parts) if p == "images")
        sub = parts[idx + 1 :]
    except StopIteration:
        sub = parts[-2:] if len(parts) >= 2 else parts
    return "-".join(sub)


def _localize_one(ref: str, src_root: Path, images_dir: Path) -> tuple[Path, str | None] | None:
    """Copy one ref's file into ``images_dir`` if it resolves safely.

    Returns ``(present_path, rewrite_target | None)``, or None to skip
    (ref kept untouched).
    """
    candidate = (src_root / ref).resolve()
    # A converted doc is untrusted input: a `../../etc/x.png` ref must not
    # exfiltrate-by-copy.
    if not candidate.is_relative_to(src_root):
        logger.warning("local_image_outside_source ref=%s", ref)
        return None
    if not candidate.is_file():
        logger.debug("local_image_missing ref=%s", ref)
        return None
    rel = Path(ref)
    canonical = len(rel.parts) == 2 and rel.parts[0] == "images"
    name = rel.name if canonical else _flat_name(rel)
    dest = images_dir / name
    rewrite = None if canonical else f"images/{name}"
    if candidate == dest.resolve():
        return dest, rewrite  # out == in: already where it belongs
    if not (dest.exists() and dest.stat().st_size == candidate.stat().st_size):
        images_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(candidate, dest)
        except OSError as e:
            logger.warning("local_image_copy_failed ref=%s error=%s", ref, e)
            return None
    return dest, rewrite


def localize_local_images_in_markdown(
    markdown: str,
    output_dir: Path,
    *,
    source_path: Path,
    images: list[Path] | None = None,
) -> tuple[str, list[Path]]:
    """Copy local relative image refs (resolved against the source's dir) into
    ``<output_dir>/images/``, retargeting non-canonical refs to the flat name.

    Returns ``(rewritten_markdown, images)`` — inputs unchanged when the
    toggle is off or nothing local resolves. A ref outside the source dir
    (traversal) or pointing at a missing file keeps its original target.
    Same contract as ``localize_remote_images_in_markdown``.
    """
    base = list(images or [])
    if not copy_local_images_enabled():
        return markdown, base

    src_root = source_path.parent.resolve()
    images_dir = output_dir / "images"
    present: list[Path] = []
    # Each unique ref is resolved once; None records a ref that did not
    # localize, so a repeat occurrence is not retried.
    resolved: dict[str, tuple[Path, str | None] | None] = {}

    def _repl(image: ImageRef) -> str | None:
        ref = image.target
        if not _is_local(ref):
            return None
        if ref not in resolved:
            localized = _localize_one(ref, src_root, images_dir)
            resolved[ref] = localized
            if localized is not None:
                present.append(localized[0])
        entry = resolved[ref]
        if entry is None or entry[1] is None:
            return None
        return image.retargeted(entry[1])

    rewritten, _ = replace_image_refs(markdown, _repl)

    seen = {str(p) for p in base}
    for p in present:
        if str(p) not in seen:
            seen.add(str(p))
            base.append(p)
    if present:
        logger.debug("local_images_localized ok=%d of=%d", len(present), len(resolved))
    return rewritten, base
