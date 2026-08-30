"""Image-ref integrity detector for `pagespeak audit`.

Separate from `_audit_checks.py` because it is the one detector that reasons
about the ref parser rather than about prose shapes.
"""

from __future__ import annotations

import re

from ._audit_finding import AuditFinding
from ._fences import fence_flags
from ._image_refs import parse_image_refs

_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# How far past a `![` to look for the rest of the ref. A real alt is short.
# Unbounded, a stray `![` swallows the prose up to a distant target, and the
# re-parse cost is quadratic in the number of stray `![` — a large code-heavy
# document goes from seconds to hours. Do not remove without re-measuring on
# a document carrying thousands of them.
_REF_REPAIR_WINDOW = 2000


def _scannable(text: str) -> str:
    """`text` with fenced-code lines and inline-code spans blanked, offsets
    preserved so a hit's index still addresses the original."""
    lines = text.splitlines(keepends=True)
    fenced = {i for i, flag in enumerate(fence_flags(text.splitlines())) if flag}
    return "".join(
        " " * len(line)
        if i in fenced
        else _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)
        for i, line in enumerate(lines)
    )


def _repairable_by_flattening(text: str, start: int) -> bool:
    """Whether the `![` at `start` reads as a ref once whitespace is collapsed.

    A bare `![` proves nothing — `!` before a bracket is ordinary in code
    (`!['a','b'].includes(x)`), and a shortcut reference image (`![Figure 1]`)
    has no inline target. Bounded so a later unrelated `](` cannot vouch for
    this one.

    A repaired alt carries no square bracket: one means the scan reached past
    the stray marker into a following link and borrowed its `]`. Costs the odd
    real defect whose alt has a bracket, which beats calling prose an error.
    """
    collapsed = " ".join(text[start : start + _REF_REPAIR_WINDOW].split())
    refs = parse_image_refs(collapsed)
    if not refs or refs[0].span[0] != 0:
        return False
    return "[" not in refs[0].alt and "]" not in refs[0].alt


def check_broken_image_ref(text: str) -> list[AuditFinding]:
    """An image ref whose alt voids it, so `parse_image_refs` reads nothing.

    No other check sees these: an unparsed ref is skipped by every later pass,
    and `dangling_image_ref` is itself parser-gated. Fix at the site that built
    the ref (`utils._alt.flatten_alt`), never by loosening the parser.

    Four-space indentation is NOT treated as a code block: in converted output
    it is nested-list content, where broken refs actually occur.
    """
    covered = {i for ref in parse_image_refs(text) for i in range(*ref.span)}
    scannable = _scannable(text)
    findings: list[AuditFinding] = []
    start = scannable.find("![")
    while start != -1:
        escaped = start > 0 and text[start - 1] == "\\"
        if start not in covered and not escaped and _repairable_by_flattening(text, start):
            snippet = " ".join(text[start : start + 60].split())
            findings.append(
                AuditFinding(
                    check="broken_image_ref",
                    severity="error",
                    line=text.count("\n", 0, start) + 1,
                    message=f"alt text breaks this image ref, so no pass can see it: {snippet!r}",
                )
            )
        start = scannable.find("![", start + 2)
    return findings
