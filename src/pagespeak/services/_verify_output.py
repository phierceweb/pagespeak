"""Verify checks on a document's picture files: links that point nowhere and
files nothing shows; also each shown picture's perceptual hash, which the
caption checks look captions up by.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pw_foundation.log import get_logger

from ..utils._phash import compute_phash
from ._deliver import is_delivered
from ._image_refs import EXTERNAL_SCHEMES, parse_image_refs, ref_paths
from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult, VerifyFinding, finding_key

logger = get_logger(__name__)

_MERMAID_TAG_RE = re.compile(r'pagespeak-image="([^"]+)"')


def is_remote(target: str) -> bool:
    """A URL (any letter case, or scheme-relative `//host/…`) or inline data rather than a local file."""
    return target.lower().startswith(EXTERNAL_SCHEMES) or target.startswith("//")


def local_target(md: Path, target: str) -> Path | None:
    """The file a local ref points at (see `ref_paths`); None for a remote one."""
    paths = ref_paths(target)
    if not paths:
        return None
    return next((md.parent / p for p in paths if (md.parent / p).exists()), md.parent / paths[-1])


def _text(doc: VerifyDoc, md: Path) -> str:
    return doc.master_text if md == doc.master else md.read_text(encoding="utf-8", errors="replace")


def _as_listed(root: str, rel: str, listings: dict[str, dict[str, str]]) -> str:
    """`rel` under `root` spelled as each folder lists its entries: a disk that
    ignores letter case finds a file under another spelling."""
    here, spelled = root, []
    for part in Path(rel).parts:
        if here not in listings:
            try:
                listings[here] = {name.casefold(): name for name in os.listdir(here)}
            except OSError:
                return rel
        name = listings[here].get(part.casefold(), part)
        spelled.append(name)
        here = os.path.join(here, name)
    return "/".join(spelled)


def check_image_links(doc: VerifyDoc) -> CheckResult:
    """Image refs in the master or a section file whose file does not exist, or
    is one `deliver` does not copy (`is_delivered`)."""
    findings: list[VerifyFinding] = []
    root = os.path.abspath(doc.root)
    listings: dict[str, dict[str, str]] = {}
    for md in (doc.master, *doc.section_files):
        rel = md.relative_to(doc.root).as_posix()
        for ref in parse_image_refs(_text(doc, md)):
            path = local_target(md, ref.target)
            if path is None:
                continue
            inside = Path(os.path.relpath(os.path.abspath(path), root)).as_posix()
            if not path.exists():
                message = f"picture file not found: {ref.target}"
            elif os.path.commonpath([root, os.path.abspath(path)]) != root:
                message = f"picture outside the document folder, so deliver leaves it behind: {ref.target}"
            elif (listed := _as_listed(root, inside, listings)) != inside:
                message = (
                    f"picture path differs in letter case from the file on disk ({listed}), "
                    f"so it breaks on a disk that tells cases apart: {ref.target}"
                )
            elif not is_delivered(Path(inside)):
                message = f"picture outside images/ and sections/, or a dot-file, so deliver leaves it behind: {ref.target}"
            else:
                continue
            key = finding_key("image_links", rel, ref.target)
            findings.append(VerifyFinding("image_links", key, f"{rel}:{ref.line}", message))
    return CheckResult("image_links", tuple(findings))


def _shown_files(doc: VerifyDoc) -> set[Path]:
    shown: set[Path] = set()
    for md in (doc.master, *doc.section_files):
        text = _text(doc, md)
        targets = [r.target for r in parse_image_refs(text)] + _MERMAID_TAG_RE.findall(text)
        for target in targets:
            path = local_target(md, target)
            if path is not None and path.exists():
                shown.add(path.resolve())
    return shown


def check_orphan_images(doc: VerifyDoc, *, pictures: set[str] | None) -> CheckResult:
    """Files in `images/` that nothing shows. A picture the build says it cut
    (`pictures`, from the source map) is lost content; any other is a note —
    the decoration pass leaves the files of the refs it removes."""
    if not doc.images_dir.is_dir():
        return CheckResult("orphan_images")
    shown = _shown_files(doc)
    findings: list[VerifyFinding] = []
    for img in sorted(doc.images_dir.rglob("*")):
        if not img.is_file() or img.name.startswith(".") or img.resolve() in shown:
            continue
        cut = pictures is not None and img.name in pictures
        message = (
            "the build cut this picture but nothing shows it"
            if cut
            else "picture file shown nowhere (unused, or a removed decoration)"
        )
        rel = img.relative_to(doc.root).as_posix()
        findings.append(
            VerifyFinding(
                "orphan_images", finding_key("orphan_images", img.name), rel, message, blocking=cut
            )
        )
    return CheckResult("orphan_images", tuple(findings))


def phash_by_image(doc: VerifyDoc) -> dict[Path, str | None]:
    """Each local picture the master shows → its perceptual hash (None: unreadable)."""
    out: dict[Path, str | None] = {}
    for ref in parse_image_refs(doc.master_text):
        path = local_target(doc.master, ref.target)
        if path is None or not path.exists() or path in out:
            continue
        try:
            out[path] = compute_phash(path)
        except (OSError, ValueError) as exc:  # a vector or damaged picture has no phash
            logger.debug("verify_phash_failed path=%s error=%s", path, exc)
            out[path] = None
    return out
