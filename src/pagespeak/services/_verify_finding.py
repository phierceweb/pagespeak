"""What `pagespeak verify` reports: findings, and whether each check ran.

A finding's `key` names the defect by what it is (a page and its text, a file
name), never by output line number, so an accepted finding stays accepted
when the document is rebuilt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pw_foundation.utils.hashing import content_hash

_WS_RE = re.compile(r"\s+")
_KEY_PART_CHARS = 80


def _capped(part: str) -> str:
    if len(part) <= _KEY_PART_CHARS:
        return part
    return f"{part[: _KEY_PART_CHARS - 9]}~{content_hash(part)[:8]}"


def finding_key(check: str, *parts: object) -> str:
    """`check:part:…`, whitespace collapsed; a part past the cap ends in a digest of all of it."""
    return ":".join([check, *(_capped(_WS_RE.sub(" ", str(p)).strip()) for p in parts)])


@dataclass(frozen=True)
class VerifyFinding:
    """One defect. A blocking finding fails the document; a note never does."""

    check: str
    key: str
    where: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class CheckResult:
    """A check's findings, or why it did not run (`skipped`)."""

    check: str
    findings: tuple[VerifyFinding, ...] = ()
    skipped: str | None = None

    @property
    def ran(self) -> bool:
        return self.skipped is None
