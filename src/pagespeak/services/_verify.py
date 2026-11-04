"""`pagespeak verify`: run every check on a converted document, write its verdict.

Also the `deliver` gate: a document whose verdict fails is not handed off.
The gate reuses the last verdict while the document's fingerprint (its output
files, captions, accept list and run record) is unchanged, and ignores
`delivery_match` — delivering is what brings a stale delivery up to date.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pw_core.pipeline.run_record import file_sha256
from pw_foundation.exceptions import InvalidInputError, PreconditionError
from pw_foundation.log import get_logger
from pw_foundation.utils.hashing import content_hash

from ._deliver import is_delivered
from ._run_record import RUN_RECORD_FILENAME
from ._source_map import SOURCE_MAP_FILENAME, SourceMap, read_source_map
from ._verify_captions import (
    check_captions,
    check_doubting_captions,
    check_shared_captions,
    pre_vision_checkpoint,
)
from ._verify_delivery import check_delivery
from ._verify_doc import VerifyDoc, default_in_dir, delivery_dir, find_documents
from ._verify_finding import CheckResult, VerifyFinding, finding_key
from ._verify_output import check_image_links, check_orphan_images, phash_by_image
from ._verify_pictures import min_dropped_ink
from ._verify_source import locate_pdf, source_checks
from ._verify_split import check_split
from ._verify_structure import check_structure
from ._verify_verdict import (
    ACCEPTED_FILENAME,
    VERDICT_MD_FILENAME,
    Verdict,
    load_accepted,
    read_stored_verdict,
    write_verdict,
)

logger = get_logger(__name__)

_DELIVERY_CHECK = "delivery_match"


def _fingerprinted_files(doc: VerifyDoc) -> list[Path]:
    files = [doc.master, doc.root / RUN_RECORD_FILENAME, doc.root / ACCEPTED_FILENAME]
    files.append(doc.root / SOURCE_MAP_FILENAME)
    if (titles := pre_vision_checkpoint(doc)) is not None:
        files.append(titles)
    for sub in ("sections", "images"):
        if (doc.root / sub).is_dir():
            files += sorted(
                p
                for p in (doc.root / sub).rglob("*")
                if p.is_file() and is_delivered(p.relative_to(doc.root))
            )
    return [p for p in files if p.is_file()]


def fingerprint(doc: VerifyDoc, source: Path | None) -> str:
    """A digest of everything a verdict depends on except the delivered copy,
    including the bytes of the source PDF it was checked against (None: none was found)."""
    from .. import __version__

    cache = doc.root / ".vision-cache"
    captions = sorted(p.name for p in cache.glob("*.json")) if cache.is_dir() else []
    files = [
        (p.relative_to(doc.root).as_posix(), file_sha256(p)) for p in _fingerprinted_files(doc)
    ]
    try:
        found = None if source is None else file_sha256(source)
    except OSError:  # unreadable now, so the source checks could not read it either
        found = None
    digest: str = content_hash([__version__, files, captions, found, min_dropped_ink()])
    return digest


def _unreadable(doc: VerifyDoc, check: str, name: str, exc: InvalidInputError) -> CheckResult:
    """A file verify cannot read, keyed by its bytes: accepting one broken copy
    accepts nothing a later edit breaks."""
    try:
        digest = file_sha256(doc.root / name)[:12]
    except OSError:
        digest = "no-bytes"
    key = finding_key(check, "unreadable", digest)
    return CheckResult(check, (VerifyFinding(check, key, name, str(exc)),))


def _accepted(doc: VerifyDoc) -> tuple[dict[str, str], CheckResult | None]:
    try:
        return load_accepted(doc.root), None
    except InvalidInputError as exc:
        return {}, _unreadable(doc, "accepted_list", ACCEPTED_FILENAME, exc)


def _source_map(doc: VerifyDoc) -> tuple[SourceMap | None, CheckResult | None]:
    try:
        return read_source_map(doc.root), None
    except InvalidInputError as exc:
        return None, _unreadable(doc, "source_map", SOURCE_MAP_FILENAME, exc)


def verify_document(
    doc: VerifyDoc, *, in_dir: Path | None = None, include_delivery: bool = True
) -> Verdict:
    """Run every check on one document; `in_dir` is where to look for its source PDF
    (default `default_in_dir`). Writes nothing."""
    phashes = phash_by_image(doc)
    smap, map_problem = _source_map(doc)
    located = locate_pdf(doc, smap, in_dir or default_in_dir(doc.root))
    results = [
        check_image_links(doc),
        check_orphan_images(
            doc, pictures=None if smap is None else {p.image for p in smap.pictures}
        ),
        check_captions(doc, phashes),
        check_shared_captions(doc, phashes),
        check_doubting_captions(doc),
        check_split(doc),
        check_structure(doc),
        *source_checks(doc, smap, located),
    ]
    if include_delivery:
        results.append(check_delivery(doc, delivery_dir(doc.root)))
    accepted, accept_problem = _accepted(doc)
    results += [p for p in (map_problem, accept_problem) if p is not None]
    checked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Verdict(doc, tuple(results), accepted, fingerprint(doc, located[0]), checked_at)


def verify_paths(
    paths: list[Path], *, in_dir: Path | None = None, include_delivery: bool = True
) -> list[Verdict]:
    """Verify every document under each path and write each verdict beside its master.

    Raises InvalidInputError for a path holding no converted document.
    """
    found: list[VerifyDoc] = []
    for path in paths:
        docs = find_documents(path)
        if not docs:
            raise InvalidInputError(f"no converted document (a master .md) under {path}")
        found += docs
    verdicts: list[Verdict] = []
    for doc in found:
        verdict = verify_document(doc, in_dir=in_dir, include_delivery=include_delivery)
        write_verdict(verdict)
        logger.info(
            "verify_document doc=%s passed=%s failing=%d",
            doc.root,
            verdict.passed,
            len(verdict.failing),
        )
        verdicts.append(verdict)
    return verdicts


def _failing_keys(doc: VerifyDoc, in_dir: Path | None) -> list[str]:
    in_dir = in_dir or default_in_dir(doc.root)
    source, _ = locate_pdf(doc, _source_map(doc)[0], in_dir)
    stored = read_stored_verdict(doc) or {}
    failing = stored.get("failing")
    if isinstance(failing, list) and stored.get("fingerprint") == fingerprint(doc, source):
        keys = [str(k) for k in failing]
    else:
        verdict = verify_document(doc, in_dir=in_dir, include_delivery=False)
        write_verdict(verdict)
        keys = [f.key for f in verdict.failing]
    return [k for k in keys if not k.startswith(f"{_DELIVERY_CHECK}:")]


def require_deliverable(source: Path, *, in_dir: Path | None = None) -> list[VerifyDoc]:
    """The documents under `source`; raises PreconditionError while any fails verify."""
    try:
        docs = find_documents(source)
    except InvalidInputError as exc:
        raise PreconditionError(f"delivery refused: {exc}") from exc
    refused: list[str] = []
    for doc in docs:
        keys = _failing_keys(doc, in_dir)
        if keys:
            by_check = Counter(k.split(":", 1)[0] for k in keys)
            counts = ", ".join(f"{check} {n}" for check, n in sorted(by_check.items()))
            refused.append(
                f"{doc.name}: {len(keys)} failing ({counts}) — {doc.root / VERDICT_MD_FILENAME}"
            )
    if refused:
        raise PreconditionError(
            "delivery refused: fix or accept each failing finding first\n" + "\n".join(refused)
        )
    return docs
