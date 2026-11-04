"""Tests for services._verify_verdict — accepted findings, PASS/FAIL, the verdict files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pw_foundation.exceptions import InvalidInputError

from pagespeak.services._verify_doc import VerifyDoc
from pagespeak.services._verify_finding import CheckResult, VerifyFinding
from pagespeak.services._verify_verdict import (
    Verdict,
    load_accepted,
    read_stored_verdict,
    render_verdict,
    write_verdict,
)


def _doc(tmp_path: Path) -> VerifyDoc:
    (tmp_path / "book.md").write_text("# Book\n", encoding="utf-8")
    return VerifyDoc(tmp_path, tmp_path / "book.md")


def _finding(key: str, *, blocking: bool = True) -> VerifyFinding:
    check = key.split(":", 1)[0]
    return VerifyFinding(check, key, "book.md:3", f"message for {key}", blocking)


def _verdict(
    doc: VerifyDoc, *findings: VerifyFinding, accepted: dict[str, str] | None = None
) -> Verdict:
    results = (
        CheckResult("captions", tuple(f for f in findings if f.check == "captions")),
        CheckResult("structure", tuple(f for f in findings if f.check == "structure")),
        CheckResult("line_coverage", skipped="no source map"),
    )
    return Verdict(
        doc, results, accepted or {}, fingerprint="abc", checked_at="2026-10-31T12:00:00Z"
    )


def test_an_unaccepted_blocking_finding_fails(tmp_path: Path) -> None:
    verdict = _verdict(
        _doc(tmp_path), _finding("captions:a.png"), _finding("structure:x", blocking=False)
    )
    assert not verdict.passed
    assert [f.key for f in verdict.failing] == ["captions:a.png"]


def test_notes_and_accepted_findings_pass(tmp_path: Path) -> None:
    verdict = _verdict(
        _doc(tmp_path),
        _finding("captions:a.png"),
        _finding("structure:x", blocking=False),
        accepted={"captions:a.png": "decorative rule, no caption needed"},
    )
    assert verdict.passed
    assert [(f.key, why) for f, why in verdict.accepted_findings] == [
        ("captions:a.png", "decorative rule, no caption needed")
    ]


def test_an_accept_no_finding_matches_is_listed_as_stale(tmp_path: Path) -> None:
    verdict = _verdict(_doc(tmp_path), accepted={"captions:gone.png": "old"})
    assert verdict.stale_accepts == ["captions:gone.png"]


def test_the_verdict_says_a_stale_accept_may_need_accepting_under_a_new_key(
    tmp_path: Path,
) -> None:
    text = render_verdict(_verdict(_doc(tmp_path), accepted={"captions:gone.png": "old"}))
    assert "accept it again under its new key" in text
    assert "- `captions:gone.png` — old" in text


def test_the_verdict_names_each_failure_with_its_key_and_says_what_did_not_run(
    tmp_path: Path,
) -> None:
    verdict = _verdict(_doc(tmp_path), _finding("captions:a.png"))
    text = render_verdict(verdict)
    assert text.splitlines()[0] == "# Verify: book — FAIL"
    assert "`captions:a.png`" in text
    assert "| line_coverage | did not run: no source map |" in text


def test_load_accepted_reads_keys_and_reasons(tmp_path: Path) -> None:
    accepted = {"accepted": [{"key": "captions:a.png", "why": "a rule"}]}
    (tmp_path / ".pagespeak-accepted.json").write_text(json.dumps(accepted), encoding="utf-8")
    assert load_accepted(tmp_path) == {"captions:a.png": "a rule"}
    assert load_accepted(tmp_path / "nowhere") == {}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"accepted": [{"key": "x"}]}',
        '{"accepted": [{"key": "x", "why": "  "}]}',
        '{"accepted": "x"}',
        '[{"key": "x", "why": "y"}]',
    ],
)
def test_a_malformed_accept_list_is_refused(tmp_path: Path, content: str) -> None:
    (tmp_path / ".pagespeak-accepted.json").write_text(content, encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_accepted(tmp_path)


def test_write_then_read_back_the_stored_verdict(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    md_path = write_verdict(_verdict(doc, _finding("captions:a.png")))
    assert md_path == tmp_path / ".pagespeak-verdict.md"
    stored = read_stored_verdict(doc)
    assert stored is not None
    assert stored["fingerprint"] == "abc"
    assert stored["failing"] == ["captions:a.png"]
