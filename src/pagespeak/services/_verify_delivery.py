"""Verify check `delivery_match`: the delivered copy is the current build.

`deliver` rebuilds its folder from the out-dir, so a delivery that differs
from the out-dir is one the last rebuild never reached.
"""

from __future__ import annotations

import filecmp
from pathlib import Path

from ._deliver import is_delivered, is_master_md
from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult, VerifyFinding, finding_key

_DELIVERED_DIRS = ("images", "sections")
_MAX_NAMED = 5


def _files(root: Path, masters: list[Path]) -> dict[str, Path]:
    """One document's delivered files under `root`: its master(s), and the files
    in sections/ and images/ that `deliver` hands off."""
    out = {m.name: m for m in masters}
    for sub in _DELIVERED_DIRS:
        if (root / sub).is_dir():
            for path in sorted((root / sub).rglob("*")):
                rel = path.relative_to(root)
                if path.is_file() and is_delivered(rel):
                    out[rel.as_posix()] = path
    return out


def _named(paths: list[str]) -> str:
    more = len(paths) - _MAX_NAMED
    return ", ".join(paths[:_MAX_NAMED]) + (f" (+{more} more)" if more > 0 else "")


def check_delivery(doc: VerifyDoc, dest: Path | None) -> CheckResult:
    """Compare the out-dir's deliverables with the delivery folder `dest`, byte for byte."""
    if dest is None:
        return CheckResult(
            "delivery_match",
            skipped="not under a conversions/out folder, so no delivery to compare",
        )
    if not dest.is_dir():
        zipped = dest.with_name(f"{dest.name}.zip")
        if zipped.is_file():
            return CheckResult(
                "delivery_match", skipped=f"delivered as {zipped.name}, not compared"
            )
        return CheckResult("delivery_match", skipped=f"not delivered (no {dest})")
    built = _files(doc.root, [doc.master])
    delivered_masters = [p for p in dest.iterdir() if p.is_file() and is_master_md(p.name)]
    delivered = _files(dest, delivered_masters)
    groups = (
        ("differs", [r for r in built if r in delivered and not _same(built[r], delivered[r])]),
        ("missing", [r for r in built if r not in delivered]),
        ("extra", [r for r in delivered if r not in built]),
    )
    verbs = {
        "differs": "differ from the build",
        "missing": "are in the build but not delivered",
        "extra": "are delivered but no longer built",
    }
    findings = tuple(
        VerifyFinding(
            "delivery_match",
            finding_key("delivery_match", kind),
            str(dest),
            f"{len(paths)} file(s) {verbs[kind]}: {_named(paths)}",
        )
        for kind, paths in groups
        if paths
    )
    return CheckResult("delivery_match", findings)


def _same(a: Path, b: Path) -> bool:
    return filecmp.cmp(a, b, shallow=False)
