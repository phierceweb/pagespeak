"""Tests for services._verify_finding — what a verify check reports."""

from __future__ import annotations

from pagespeak.services._verify_finding import CheckResult, VerifyFinding, finding_key


def test_finding_key_collapses_whitespace_so_a_rewrapped_line_keeps_its_key() -> None:
    assert (
        finding_key("lost_line", "p4", "the  quick\nbrown fox")
        == "lost_line:p4:the quick brown fox"
    )


def test_finding_key_caps_each_part() -> None:
    key = finding_key("lost_line", "x" * 500)
    assert len(key) == len("lost_line:") + 80
    assert key.startswith("lost_line:" + "x" * 71)


def test_finding_key_keeps_long_parts_apart() -> None:
    long = "a" * 90
    assert finding_key("image_links", f"{long}-1.png") != finding_key(
        "image_links", f"{long}-2.png"
    )


def test_a_check_that_did_not_run_says_why() -> None:
    result = CheckResult("line_coverage", skipped="no source map")
    assert not result.ran
    assert CheckResult("line_coverage").ran


def test_findings_block_unless_marked_as_notes() -> None:
    assert VerifyFinding("c", "c:k", "here", "msg").blocking
    assert not VerifyFinding("c", "c:k", "here", "msg", blocking=False).blocking
