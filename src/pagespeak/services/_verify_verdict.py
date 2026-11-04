"""The verdict on one document: accepted findings, PASS/FAIL, and its files.

`<doc>/.pagespeak-accepted.json` lists findings a person has looked at and
accepted: `{"accepted": [{"key": "…", "why": "…"}]}`. An accepted finding is
still listed, with its reason, but no longer fails the document. The verdict
is written beside the master as `.pagespeak-verdict.md` for people and
`.pagespeak-verdict.json` for `deliver`, which reuses it while the document
is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pw_foundation.exceptions import InvalidInputError
from pw_foundation.utils.io import atomic_write_json, atomic_write_text

from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult, VerifyFinding

ACCEPTED_FILENAME = ".pagespeak-accepted.json"
VERDICT_MD_FILENAME = ".pagespeak-verdict.md"
VERDICT_JSON_FILENAME = ".pagespeak-verdict.json"
_MAX_NOTES_SHOWN = 50


@dataclass(frozen=True)
class Verdict:
    doc: VerifyDoc
    results: tuple[CheckResult, ...]
    accepted: dict[str, str]
    fingerprint: str
    checked_at: str

    @property
    def findings(self) -> list[VerifyFinding]:
        return [f for r in self.results for f in r.findings]

    @property
    def failing(self) -> list[VerifyFinding]:
        return [f for f in self.findings if f.blocking and f.key not in self.accepted]

    @property
    def accepted_findings(self) -> list[tuple[VerifyFinding, str]]:
        return [
            (f, self.accepted[f.key])
            for f in self.findings
            if f.blocking and f.key in self.accepted
        ]

    @property
    def notes(self) -> list[VerifyFinding]:
        return [f for f in self.findings if not f.blocking]

    @property
    def stale_accepts(self) -> list[str]:
        keys = {f.key for f in self.findings}
        return [k for k in self.accepted if k not in keys]

    @property
    def passed(self) -> bool:
        return not self.failing


def load_accepted(root: Path) -> dict[str, str]:
    """key → why from `<root>/.pagespeak-accepted.json`; {} when there is none.

    Raises InvalidInputError for a malformed list: a broken file must never
    read as "nothing accepted" and silently change a verdict.
    """
    path = root / ACCEPTED_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInputError(f"{path}: not readable JSON ({exc})") from exc
    entries = data.get("accepted") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(_is_entry(e) for e in entries):
        raise InvalidInputError(f'{path}: expected {{"accepted": [{{"key": "…", "why": "…"}}, …]}}')
    return {e["key"]: e["why"] for e in entries}


def _is_entry(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("key"), str)
        and isinstance(entry.get("why"), str)
        and bool(entry["why"].strip())
    )


def _line(f: VerifyFinding, why: str | None = None) -> str:
    accepted = f" — accepted: {why}" if why is not None else ""
    return f"- `{f.where}` {f.message}{accepted} (key `{f.key}`)"


def _grouped(findings: list[VerifyFinding]) -> dict[str, list[VerifyFinding]]:
    groups: dict[str, list[VerifyFinding]] = {}
    for f in findings:
        groups.setdefault(f.check, []).append(f)
    return groups


def _summary_rows(verdict: Verdict) -> list[str]:
    rows = ["| Check | Result |", "|---|---|"]
    for r in verdict.results:
        if not r.ran:
            rows.append(f"| {r.check} | did not run: {r.skipped} |")
            continue
        failing = sum(1 for f in r.findings if f.blocking and f.key not in verdict.accepted)
        accepted = sum(1 for f in r.findings if f.blocking and f.key in verdict.accepted)
        notes = sum(1 for f in r.findings if not f.blocking)
        parts = [
            f"{n} {label}"
            for n, label in ((failing, "failing"), (accepted, "accepted"), (notes, "notes"))
            if n
        ]
        rows.append(f"| {r.check} | {', '.join(parts) or 'clean'} |")
    return rows


def render_verdict(verdict: Verdict) -> str:
    """The verdict as markdown: summary table, then every failing and accepted
    finding with its key, then notes (capped per check)."""
    word = "PASS" if verdict.passed else "FAIL"
    out = [f"# Verify: {verdict.doc.name} — {word}", ""]
    out.append(
        f"{len(verdict.failing)} failing, {len(verdict.accepted_findings)} accepted, "
        f"{len(verdict.notes)} notes. Checked {verdict.checked_at}. To accept a finding after "
        f"reading it, add its key and a reason to `{ACCEPTED_FILENAME}` in the document folder."
    )
    out += ["", *_summary_rows(verdict)]
    if verdict.failing:
        out += ["", f"## Failing ({len(verdict.failing)})"]
        for check, group in _grouped(verdict.failing).items():
            out += ["", f"### {check} ({len(group)})", "", *(_line(f) for f in group)]
    if verdict.accepted_findings:
        out += ["", f"## Accepted ({len(verdict.accepted_findings)})", ""]
        out += [_line(f, why) for f, why in verdict.accepted_findings]
    if verdict.notes:
        out += ["", f"## Notes ({len(verdict.notes)})"]
        for check, group in _grouped(verdict.notes).items():
            out += [
                "",
                f"### {check} ({len(group)})",
                "",
                *(_line(f) for f in group[:_MAX_NOTES_SHOWN]),
            ]
            if len(group) > _MAX_NOTES_SHOWN:
                out.append(f"- … and {len(group) - _MAX_NOTES_SHOWN} more")
    if verdict.stale_accepts:
        out += ["", "## Accepted keys no finding has", ""]
        out.append(
            "Fixed since, or a newer pagespeak names the finding differently: if it is "
            "still listed above, read it and accept it again under its new key."
        )
        out.append("")
        out += [f"- `{k}` — {verdict.accepted[k]}" for k in verdict.stale_accepts]
    return "\n".join(out) + "\n"


def render_summary(verdicts: list[Verdict]) -> str:
    """One line per document, then the checks that did not run, then a total."""
    out: list[str] = []
    for v in verdicts:
        if v.passed:
            line = f"PASS  {v.doc.name}"
            if v.accepted_findings or v.notes:
                line += f"  ({len(v.accepted_findings)} accepted, {len(v.notes)} notes)"
        else:
            groups = _grouped(v.failing)
            counts = ", ".join(f"{check} {len(g)}" for check, g in groups.items())
            line = f"FAIL  {v.doc.name}  {len(v.failing)} failing: {counts}"
        out.append(f"{line}  → {v.doc.root / VERDICT_MD_FILENAME}")
        skipped = [f"{r.check} ({r.skipped})" for r in v.results if not r.ran]
        if skipped:
            out.append(f"      did not run: {'; '.join(skipped)}")
    failed = sum(1 for v in verdicts if not v.passed)
    out.append(f"{len(verdicts)} document(s): {len(verdicts) - failed} pass, {failed} fail")
    return "\n".join(out)


def write_verdict(verdict: Verdict) -> Path:
    """Write the markdown and JSON verdicts beside the master; returns the markdown path."""
    root = verdict.doc.root
    md_path = root / VERDICT_MD_FILENAME
    atomic_write_text(md_path, render_verdict(verdict))
    stored = {
        "document": verdict.doc.master.name,
        "fingerprint": verdict.fingerprint,
        "checked_at": verdict.checked_at,
        "passed": verdict.passed,
        "failing": [f.key for f in verdict.failing],
        "skipped": {r.check: r.skipped for r in verdict.results if not r.ran},
    }
    atomic_write_json(root / VERDICT_JSON_FILENAME, stored)
    return md_path


def read_stored_verdict(doc: VerifyDoc) -> dict[str, Any] | None:
    """The JSON verdict last written for `doc`, or None when absent or unreadable."""
    path = doc.root / VERDICT_JSON_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("document") == doc.master.name else None
