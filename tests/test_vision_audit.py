"""Tests for services/_vision_audit — likely-confabulated caption detection.

Deterministic, $0. The identity-divergence check flags a figure whose
generated caption keeps NONE of its source-alt's subject words (the
"described as the wrong thing" shape). Domain-agnostic — it only compares a
caption to the author's own alt text.
"""

from __future__ import annotations

import json
from pathlib import Path

from pagespeak.services._vision_audit import (
    _subject_anchors,
    audit_vision,
    check_identity_divergence,
)

_SQUIRREL_ALT = "Photograph of a red squirrel clinging to a tree branch in a forest"


def test_subject_anchors_drops_generic_figure_words() -> None:
    assert _subject_anchors("Diagram showing a labeled cross section view") == []


def test_subject_anchors_keeps_content_nouns() -> None:
    anchors = _subject_anchors(_SQUIRREL_ALT)
    assert "squirrel" in anchors
    assert "branch" in anchors
    assert "photograph" not in anchors  # generic filler, ignored


def test_flags_caption_that_shares_no_alt_subject() -> None:
    alts = {"fig1.webp": _SQUIRREL_ALT}
    caps = {"fig1.webp": "A lemur with large round eyes staring directly at the camera."}
    findings = check_identity_divergence(alts, caps)
    assert len(findings) == 1
    assert findings[0].image == "fig1.webp"
    assert findings[0].check == "identity_divergence"
    assert findings[0].source_alt == _SQUIRREL_ALT


def test_keeps_caption_that_echoes_the_alt_subject() -> None:
    alts = {"fig1.webp": _SQUIRREL_ALT}
    caps = {"fig1.webp": "A red squirrel on a branch, bushy tail visible."}
    assert check_identity_divergence(alts, caps) == []


def test_skips_thin_alt() -> None:
    # alt shorter than the clear-subject threshold — not assessable, not flagged.
    alts = {"fig1.webp": "A squirrel"}
    caps = {"fig1.webp": "A lemur on a branch."}
    assert check_identity_divergence(alts, caps) == []


def test_skips_alt_with_only_generic_words() -> None:
    # all-generic alt → no subject anchors → not assessable (no false flag).
    alts = {"fig1.webp": "Diagram showing a labeled cross section view of it"}
    caps = {"fig1.webp": "A completely unrelated caption about a car engine."}
    assert check_identity_divergence(alts, caps) == []


def _seed_doc(tmp_path: Path, *, alt: str, caption: str, basename: str = "fig1.webp") -> Path:
    """A minimal out-dir: a structured checkpoint (source alt) + one cached caption."""
    (tmp_path / "doc.structured.md").write_text(
        f"# Doc\n\n![{alt}](images/{basename})\n", encoding="utf-8"
    )
    cache = tmp_path / ".vision-cache"
    cache.mkdir()
    (cache / "hash1.json").write_text(
        json.dumps({"caption": caption, "source_paths": [basename], "phash": "hash1"}),
        encoding="utf-8",
    )
    return tmp_path


def test_audit_vision_walks_a_doc_dir_and_flags(tmp_path: Path) -> None:
    doc = _seed_doc(tmp_path, alt=_SQUIRREL_ALT, caption="A lemur staring at the camera.")
    report = audit_vision([doc])
    assert report.docs_scanned == 1
    assert report.figures_assessed == 1
    assert len(report.findings_by_doc[doc]) == 1


def test_audit_vision_clean_doc_has_no_findings(tmp_path: Path) -> None:
    doc = _seed_doc(tmp_path, alt=_SQUIRREL_ALT, caption="A red squirrel on a branch.")
    report = audit_vision([doc])
    assert report.figures_assessed == 1
    assert report.findings_by_doc == {}
