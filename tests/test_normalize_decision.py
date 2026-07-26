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


# ── re-leveling downgrade on an outline-derived hierarchy ───────────────
#
# `llm`/`llm_full` reassign every heading's depth. When the depth came from
# the source's own bookmark outline that is destructive, so the mode drops to
# `llm_dehead`, which removes junk without touching levels.


def _pdf(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return p


def test_releveling_modes_downgrade_when_hierarchy_is_authoritative(monkeypatch, tmp_path):
    import pagespeak.services._hierarchy_trust as ht
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _s: 4)
    for mode in ("llm", "llm_full"):
        got = route_authoritative_hierarchy(
            mode, _pdf(tmp_path), pdf_backend="docling", heading_hierarchy=True
        )
        assert got == "llm_dehead", mode


def test_no_downgrade_without_an_outline(monkeypatch, tmp_path):
    import pagespeak.services._hierarchy_trust as ht
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _s: 0)
    got = route_authoritative_hierarchy(
        "llm_full", _pdf(tmp_path), pdf_backend="docling", heading_hierarchy=True
    )
    assert got == "llm_full"


def test_no_downgrade_for_marker(monkeypatch, tmp_path):
    """Marker infers depth from typography — re-leveling is the point there."""
    import pagespeak.services._hierarchy_trust as ht
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _s: 4)
    got = route_authoritative_hierarchy(
        "llm_full", _pdf(tmp_path), pdf_backend="marker", heading_hierarchy=True
    )
    assert got == "llm_full"


def test_non_releveling_modes_pass_through(monkeypatch, tmp_path):
    import pagespeak.services._hierarchy_trust as ht
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _s: 4)
    for mode in ("heuristic", "llm_dehead"):
        got = route_authoritative_hierarchy(
            mode, _pdf(tmp_path), pdf_backend="docling", heading_hierarchy=True
        )
        assert got == mode, mode


def test_downgrade_skipped_when_the_outline_tree_is_malformed() -> None:
    """An outline-derived hierarchy is only worth preserving if it is coherent.

    `llm_dehead` never changes a level, so downgrading to it on a document whose
    outline levels are themselves broken guarantees the break survives. A tree
    that skips a tier entirely (H2 -> H4 with no H3 anywhere) is the signal.
    """
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    # H2 children under H1, then H4 with tier 3 never used at all.
    malformed = "\n".join(
        ["# Title", "body"] + [f"## Section {i}\n\ntext\n\n#### Sub {i}\n\ntext" for i in range(12)]
    )
    assert (
        route_authoritative_hierarchy(
            "llm_full",
            None,
            pdf_backend="docling",
            heading_hierarchy=True,
            markdown=malformed,
            in_memory=True,
        )
        == "llm_full"
    ), "a malformed outline tree must still be re-levelled"


def test_downgrade_still_applies_to_a_well_formed_outline_tree() -> None:
    """The guard must not disable the downgrade for the case it exists for."""
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    well_formed = "\n".join(
        ["# Title", "body"] + [f"## Section {i}\n\ntext\n\n### Sub {i}\n\ntext" for i in range(12)]
    )
    assert (
        route_authoritative_hierarchy(
            "llm_full",
            None,
            pdf_backend="docling",
            heading_hierarchy=True,
            markdown=well_formed,
            in_memory=True,
        )
        == "llm_dehead"
    )


def test_no_markdown_keeps_the_old_behaviour() -> None:
    """Callers that pass no markdown are unchanged — the guard is additive."""
    from pagespeak.services._normalize_decision import route_authoritative_hierarchy

    assert (
        route_authoritative_hierarchy(
            "llm_full",
            None,
            pdf_backend="docling",
            heading_hierarchy=True,
            in_memory=True,
        )
        == "llm_dehead"
    )


def test_normalize_phase_forwards_the_markdown_to_the_router(tmp_path, monkeypatch) -> None:
    """Phase-level: without the markdown the coherence guard cannot fire.

    The unit tests above pass whether or not the phase actually supplies it —
    only asserting at the call site catches a guard that is dead in production.
    """
    import pagespeak.orchestrators._phases as phases
    from pagespeak.models._models import IngestResult

    from .test_context import _ctx as make_ctx

    seen: dict[str, object] = {}

    def spy(mode, src, **kwargs):
        seen["markdown"] = kwargs.get("markdown")
        return "llm_dehead"

    monkeypatch.setattr("pagespeak.services._normalize_decision.route_authoritative_hierarchy", spy)
    monkeypatch.setattr(
        "pagespeak.services._heading_normalize.gather_normalize_levels",
        lambda *a, **k: None,
    )

    out = tmp_path / "out"
    out.mkdir()
    ctx = make_ctx(
        src=tmp_path / "doc.pdf",
        out=out,
        cleaned_md_path=out / "doc.cleaned.md",
        normalized_md_path=out / "doc.normalized.md",
    )
    ctx.normalize_headings = True
    ctx.normalize_headings_mode = "llm_full"
    ctx.result = IngestResult(markdown="# A\n\nbody\n", images=[], source_format="pdf")
    phases.NormalizePhase().run(ctx)
    assert seen.get("markdown") is not None, "NormalizePhase did not forward the markdown"
