"""`pagespeak audit` — output-defect detection over converted markdown.

The third QA layer: `bin/lint` asks "is the code clean", `bin/validate`
asks "did a code change alter output (vs a baseline)", this asks **"is
this converted output defective"** — absolute, no baseline, $0, no LLM.

Walks final artifacts only (master `.md`, `sections/`, `INDEX.md`),
skipping stage checkpoints and dot-dirs, runs the pure text detectors
from `_audit_checks.py` plus the file-context checks below, and renders
a human-readable report. The audit narrows *where* to read — it never
replaces reading the output.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from ._audit_checks import AuditFinding, run_text_checks
from ._audit_coverage import check_text_coverage
from ._audit_extraction import run_extraction_checks
from ._image_refs import parse_image_refs

_CHECKPOINT_SUFFIXES = (
    ".raw.md",
    ".cleaned.md",
    ".normalized.md",
    ".repaired.md",
    ".structured.md",
    ".visioned.md",
)
_MAX_SHOWN_PER_CHECK = 3  # per file, in the rendered report
_MAX_NAMED_NO_SOURCE = 10

_PAGE_ANCHOR_RE = re.compile(r'<span id="page-\d+-\d+"></span>\s*')
_EXTERNAL_SCHEMES = ("http://", "https://", "data:")


@dataclass(frozen=True)
class AuditReport:
    """Aggregated findings for one audit run."""

    findings_by_file: dict[Path, list[AuditFinding]]
    files_scanned: int
    coverage_checked: int = 0
    coverage_no_source: tuple[str, ...] = ()

    @property
    def error_count(self) -> int:
        return self._count("error")

    @property
    def warning_count(self) -> int:
        return self._count("warning")

    @property
    def counts_by_check(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for findings in self.findings_by_file.values():
            counts.update(f.check for f in findings)
        return counts

    def _count(self, severity: str) -> int:
        return sum(
            1
            for findings in self.findings_by_file.values()
            for f in findings
            if f.severity == severity
        )


def check_empty_section(path: Path, text: str | None = None) -> list[AuditFinding]:
    """A `sections/` file with no body AND no subsections — a true orphan
    shell the splitter's empty-shell drop should have caught. A parent whose
    only content is a `## Subsections` list is a deliberate nav node (its
    content lives in its children) and is NOT flagged."""
    if "sections" not in path.parts:
        return []
    if text is None:
        text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "## Subsections":
            return []  # nav node: children carry the content
        if stripped.startswith("#"):
            continue
        if stripped.startswith("> ↑"):
            continue
        if _PAGE_ANCHOR_RE.fullmatch(stripped):
            continue
        return []  # real body content found
    return [
        AuditFinding(
            check="empty_section",
            severity="warning",
            line=1,
            message="section has no body and no subsections (orphan shell)",
        )
    ]


def check_dangling_image_refs(path: Path, text: str | None = None) -> list[AuditFinding]:
    """Image references whose relative target doesn't exist on disk."""
    if text is None:
        text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[AuditFinding] = []
    for ref in parse_image_refs(text):
        target = ref.target
        if target.startswith(_EXTERNAL_SCHEMES) or not target:
            continue
        # A `%`-encoded target resolves to its decoded file on disk; check both.
        if not ((path.parent / target).exists() or (path.parent / unquote(target)).exists()):
            findings.append(
                AuditFinding(
                    check="dangling_image_ref",
                    severity="error",
                    line=ref.line,
                    message=f"image target not found: {target}",
                )
            )
    return findings


def audit_file(path: Path) -> list[AuditFinding]:
    """All detectors over one markdown file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = run_text_checks(text)
    if "sections" not in path.parts:  # whole-document signatures
        findings.extend(run_extraction_checks(text))
    findings.extend(check_empty_section(path, text))
    findings.extend(check_dangling_image_refs(path, text))
    return findings


def _iter_markdown(root: Path) -> list[Path]:
    """Final-artifact .md files under root: no checkpoints, no dot-dirs."""
    files: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        if "chunks" in rel_parts[:-1]:  # chunked-parallel ingest intermediates
            continue
        if path.name.endswith(_CHECKPOINT_SUFFIXES):
            continue
        files.append(path)
    return files


def _coverage_target(doc_dir: Path) -> Path | None:
    """`<stem>.raw.md` — the backend's output, which the coverage threshold was
    calibrated on — else the master `.md`."""
    raws = sorted(doc_dir.glob("*.raw.md"))
    if raws:
        return raws[0]
    masters = [
        p
        for p in sorted(doc_dir.glob("*.md"))
        if p.name != "INDEX.md" and not p.name.endswith(_CHECKPOINT_SUFFIXES)
    ]
    return masters[0] if masters else None


def is_document_dir(path: Path) -> bool:
    """True when `path` holds one converted document (`<stem>.raw.md` or a master `.md`)."""
    return path.is_dir() and _coverage_target(path) is not None


def _coverage_doc_dirs(given: Path) -> list[Path]:
    """The given dir if it holds a converted document, else its child dirs that do."""
    if is_document_dir(given):
        return [given]
    return [d for d in sorted(given.iterdir()) if is_document_dir(d)]


def audit_paths(
    paths: list[Path], *, source_for: Callable[[Path], Path | None] | None = None
) -> AuditReport:
    """Audit every final markdown artifact under the given files/dirs.

    With `source_for` (checked file → its source PDF, or None), each converted
    document dir is also checked for text-layer coverage; every path must then
    be a dir. Raises ValueError for a file.
    """
    if source_for is not None:
        for given in paths:
            if not given.is_dir():
                raise ValueError(
                    f"text coverage is checked per converted document folder; "
                    f"pass {given.parent} rather than {given}"
                )
    findings_by_file: dict[Path, list[AuditFinding]] = {}
    scanned = 0
    for given in paths:
        targets = [given] if given.is_file() else _iter_markdown(given)
        for target in targets:
            scanned += 1
            findings = audit_file(target)
            if findings:
                findings_by_file[target] = findings
    checked, no_source = 0, []
    if source_for is not None:
        for doc_dir in (d for given in paths for d in _coverage_doc_dirs(given)):
            checked_md = _coverage_target(doc_dir)
            pdf = source_for(checked_md) if checked_md is not None else None
            if checked_md is None or pdf is None or pdf.suffix.lower() != ".pdf":
                no_source.append(doc_dir.name)
                continue
            checked += 1
            findings = check_text_coverage(checked_md, pdf)
            if findings:
                findings_by_file.setdefault(checked_md, []).extend(findings)
    return AuditReport(findings_by_file, scanned, checked, tuple(no_source))


def render_report(report: AuditReport, *, summary_only: bool = False) -> str:
    """Human-readable report: summary by check, then capped per-file detail."""
    out: list[str] = [
        f"audited {report.files_scanned} file(s): "
        f"{report.error_count} errors, {report.warning_count} warnings"
    ]
    for check, n in sorted(report.counts_by_check.items()):
        out.append(f"  {check}: {n}")
    if report.coverage_checked or report.coverage_no_source:
        line = f"text coverage: {report.coverage_checked} doc(s) checked against their source PDF"
        if report.coverage_no_source:
            names = ", ".join(report.coverage_no_source[:_MAX_NAMED_NO_SOURCE])
            extra = len(report.coverage_no_source) - _MAX_NAMED_NO_SOURCE
            line += f"; no source PDF: {names}" + (f" (+{extra} more)" if extra > 0 else "")
        out.append(line)
    if summary_only:
        return "\n".join(out)
    for path, findings in report.findings_by_file.items():
        out.append("")
        out.append(str(path))
        by_check: dict[str, list[AuditFinding]] = {}
        for f in findings:
            by_check.setdefault(f.check, []).append(f)
        for check, group in by_check.items():
            for f in group[:_MAX_SHOWN_PER_CHECK]:
                out.append(f"  {path.name}:{f.line} {f.check} — {f.message}")
            hidden = len(group) - _MAX_SHOWN_PER_CHECK
            if hidden > 0:
                out.append(f"  … and {hidden} more {check} in this file")
    return "\n".join(out)
