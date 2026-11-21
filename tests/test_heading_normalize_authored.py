"""Heading normalize on a document whose headings are all the author's.

Kept apart from `test_heading_normalize.py`, which is past its size budget.
"""

from __future__ import annotations

from pagespeak.services._heading_normalize import apply_normalization, gather_normalize_levels

MD = (
    "# Motion Book\n\nIntro.\n\n"
    "## 2 Forces\n\nForces body.\n\n### 2.1 Push\n\nPush body.\n\n"
    "## 3 Motion\n\nMotion body.\n\n### 3.1 Speed\n\nSpeed body.\n"
)


def test_heuristic_relevels_guessed_headings() -> None:
    out = apply_normalization(MD, gather_normalize_levels(MD, mode="heuristic"))
    assert "## 2.1 Push" in out
    assert "## 3.1 Speed" in out


def test_heuristic_keeps_authored_levels() -> None:
    data = gather_normalize_levels(MD, mode="heuristic", authored_levels=True)
    assert data is None
    assert apply_normalization(MD, data) == MD


def test_llm_mode_still_runs_on_authored_headings() -> None:
    calls: list[str] = []

    def fake_invoke(prompt: str) -> str:
        calls.append(prompt)
        return ""

    gather_normalize_levels(MD, mode="llm", authored_levels=True, invoke=fake_invoke)
    assert calls
