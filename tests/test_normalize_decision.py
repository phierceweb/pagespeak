"""Tests for the auto heading-normalize-mode classifier.

Synthetic heading shapes only — validation on real documents is a manual
step, not the unit suite. Tests that reach the llm_full branch monkeypatch
`_estimate_full_payload` so they don't depend on the live model_router
config / env.
"""

from __future__ import annotations

from pagespeak.services._normalize_decision import classify_normalize_mode


def _doc(headings: list[tuple[int, str]]) -> str:
    """Build markdown: each (level, text) heading followed by a body line."""
    out: list[str] = []
    for level, text in headings:
        out.append(f"{'#' * level} {text}")
        out.append("Body paragraph with enough words to be real content.")
    return "\n".join(out)


def test_few_headings_skips_llm():
    d = classify_normalize_mode(_doc([(1, "Intro"), (2, "Setup")]))
    assert d.mode == "heuristic"
    assert d.reason == "too_few_headings"


def test_healthy_hierarchy_skips_llm():
    heads = (
        [(1, "Title")] + [(2, f"Sec {i}") for i in range(3)] + [(3, f"Sub {i}") for i in range(9)]
    )
    d = classify_normalize_mode(_doc(heads))
    assert d.mode == "heuristic"
    assert d.reason == "shape_ok"


def test_small_flat_doc_skips_llm():
    # 25 same-level non-numbered headings: flat SHARE but not a LARGE
    # collapse (count < COLLAPSE_MIN) -> heuristic (the flat manual case).
    d = classify_normalize_mode(_doc([(2, f"Topic {i}") for i in range(25)]))
    assert d.mode == "heuristic"
    assert d.reason == "shape_ok"


def test_numbered_flat_doc_skips_llm():
    # 60 N.M numbered headings: numbering drives the free heuristic fix.
    heads = [(2, f"{i // 3 + 1}.{i % 3 + 1} Step") for i in range(60)]
    d = classify_normalize_mode(_doc(heads))
    assert d.mode == "heuristic"
    assert d.reason == "numbered"


def test_large_collapsed_non_numbered_needs_full(monkeypatch):
    from pagespeak.services import _normalize_decision

    monkeypatch.setattr(_normalize_decision, "_estimate_full_payload", lambda md: (50_000, 900_000))
    heads = [(1, "Book Title")] + [(2, f"Heading {i}") for i in range(80)]
    d = classify_normalize_mode(_doc(heads))
    assert d.mode == "llm_full"
    assert d.reason == "collapsed_non_numbered"
    assert d.full_payload_tokens == 50_000
    assert d.full_payload_budget == 900_000


def test_collapsed_low_share_non_numbered_needs_full(monkeypatch):
    # 40+ headings piled at the dominant level but WELL under a 70% share.
    # Collapse by absolute count is the trigger — share need not be a
    # supermajority (a well-structured pyramid is also leaf-heavy, so share
    # is a poor discriminator).
    from pagespeak.services import _normalize_decision

    monkeypatch.setattr(_normalize_decision, "_estimate_full_payload", lambda md: (50_000, 900_000))
    heads = (
        [(1, f"Top {i}") for i in range(20)]
        + [(2, f"Mid {i}") for i in range(45)]
        + [(3, f"Deep {i}") for i in range(35)]
    )
    d = classify_normalize_mode(_doc(heads))
    assert d.dominant_count == 45
    assert d.dominant_share < 0.70  # NOT flat by the 0.70 bar
    assert d.mode == "llm_full"
    assert d.reason == "collapsed_non_numbered"


def test_collapsed_but_oversized_for_config_falls_back(monkeypatch):
    from pagespeak.services import _normalize_decision

    monkeypatch.setattr(
        _normalize_decision, "_estimate_full_payload", lambda md: (999_999, 150_000)
    )
    heads = [(2, f"Heading {i}") for i in range(80)]
    d = classify_normalize_mode(_doc(heads))
    assert d.mode == "heuristic"
    assert d.reason == "needs_full_but_oversized_for_config"
    assert d.full_payload_tokens == 999_999
    assert d.full_payload_budget == 150_000


def test_decision_carries_metrics(monkeypatch):
    from pagespeak.services import _normalize_decision

    monkeypatch.setattr(_normalize_decision, "_estimate_full_payload", lambda md: (50_000, 900_000))
    d = classify_normalize_mode(_doc([(2, f"Heading {i}") for i in range(80)]))
    assert d.n_headings == 80
    assert d.dominant_count == 80
    assert 0.99 <= d.dominant_share <= 1.0
    assert d.numbered_share == 0.0


def test_resolve_normalize_mode_returns_concrete_mode(monkeypatch):
    # resolve_normalize_mode wraps the classifier + logs; returns the mode.
    from pagespeak.services import _normalize_decision

    monkeypatch.setattr(
        _normalize_decision,
        "classify_normalize_mode",
        lambda md: _normalize_decision.NormalizeDecision(
            mode="llm_full",
            reason="collapsed_non_numbered",
            n_headings=80,
            dominant_count=80,
            dominant_share=1.0,
            numbered_share=0.0,
            full_payload_tokens=50_000,
            full_payload_budget=900_000,
        ),
    )
    assert _normalize_decision.resolve_normalize_mode("# H\n\nbody") == "llm_full"
