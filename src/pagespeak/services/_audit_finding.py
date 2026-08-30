"""The finding every `pagespeak audit` detector returns.

Its own module so detector modules can share it without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditFinding:
    """One detected defect: which check fired, where, and why."""

    check: str
    severity: str  # "error" | "warning"
    line: int  # 1-based line of the (first) occurrence
    message: str
