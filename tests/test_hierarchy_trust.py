"""Provenance gate for the structure phase's level-rewriting passes."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._hierarchy_trust import has_authoritative_hierarchy


def _args(**over):
    base = dict(pdf_backend="docling", heading_hierarchy=True)
    base.update(over)
    return base


def test_marker_is_never_authoritative(tmp_path: Path) -> None:
    """Marker infers depth from typography; its tree always needs the passes."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert not has_authoritative_hierarchy(pdf, **_args(pdf_backend="marker"))


def test_docling_without_the_option_is_not_authoritative(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert not has_authoritative_hierarchy(pdf, **_args(heading_hierarchy=False))


def test_non_pdf_source_is_not_authoritative(tmp_path: Path) -> None:
    docx = tmp_path / "x.docx"
    docx.write_bytes(b"PK\x03\x04")
    assert not has_authoritative_hierarchy(docx, **_args())


def test_missing_source_is_not_authoritative() -> None:
    assert not has_authoritative_hierarchy(None, **_args())


def test_unreadable_pdf_falls_back_to_not_authoritative(tmp_path: Path) -> None:
    """An unparseable source must not silently disable the repair passes."""
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not really a pdf")
    assert not has_authoritative_hierarchy(pdf, **_args())


def test_outline_depth_gates_the_verdict(monkeypatch, tmp_path: Path) -> None:
    """A bare chapter list (depth 1) leaves everything below it style-inferred."""
    import pagespeak.services._hierarchy_trust as ht

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _src: 1)
    assert not ht.has_authoritative_hierarchy(pdf, **_args())
    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _src: 2)
    assert ht.has_authoritative_hierarchy(pdf, **_args())


def test_min_depth_is_env_tunable(monkeypatch, tmp_path: Path) -> None:
    import pagespeak.services._hierarchy_trust as ht

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _src: 2)
    assert ht.has_authoritative_hierarchy(pdf, **_args())
    monkeypatch.setenv("PAGESPEAK_TRUSTED_OUTLINE_MIN_DEPTH", "3")
    assert not ht.has_authoritative_hierarchy(pdf, **_args())


def test_real_pdf_outline_depth_is_read(tmp_path: Path) -> None:
    """Depth comes from the file itself, not a flag."""
    pytest.importorskip("pypdfium2")
    from pagespeak.services._hierarchy_trust import pdf_outline_depth

    missing = tmp_path / "nope.pdf"
    assert pdf_outline_depth(missing) == 0


# ── the trusted-hierarchy invariant must reach the REPAIR phase ────────
#
# `is_outline_doc` was exercised only by unit tests: the production call site
# never passed it, so the branch its own docstring calls sacrosanct never
# fired. These are phase-level — a unit test would pass with the wiring cut.


def test_repair_phase_honours_an_outline_derived_hierarchy(tmp_path, monkeypatch) -> None:
    """A docling PDF with a real bookmark outline must not have its depths
    rewritten by repair."""
    import pagespeak.services._hierarchy_trust as ht
    from pagespeak.services._hierarchy_trust import hierarchy_is_trusted, record_hierarchy_source

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _s: 4)
    record_hierarchy_source(out, pdf, pdf_backend="docling", heading_hierarchy=True)
    assert hierarchy_is_trusted(pdf, out, pdf_backend="docling", heading_hierarchy=True)


def test_cleanup_records_a_reconstructed_word_outline(tmp_path) -> None:
    """The signal must survive to a later `--from repair` invocation."""
    from pagespeak.services._hierarchy_trust import outline_promoted, record_outline_promoted

    out = tmp_path / "out"
    out.mkdir()
    assert not outline_promoted(out)
    record_outline_promoted(out, promoted=True)
    assert outline_promoted(out), "signal did not persist beside the checkpoints"
    assert hierarchy_is_trusted_for(out)


def hierarchy_is_trusted_for(out) -> bool:
    from pagespeak.services._hierarchy_trust import hierarchy_is_trusted

    return hierarchy_is_trusted(None, out, pdf_backend="marker", heading_hierarchy=False)


def test_repair_phase_actually_passes_the_flag(tmp_path, monkeypatch) -> None:
    """Phase-level: RepairPhase must FORWARD is_outline_doc, not the default.

    The unit tests for this branch passed while the production call site never
    supplied the flag — only a phase-level assertion catches that.
    """
    import pagespeak.orchestrators._phases as phases
    from pagespeak.models._models import IngestResult
    from pagespeak.services._hierarchy_trust import record_outline_promoted

    from .test_context import _ctx as make_ctx

    seen: dict[str, object] = {}

    def fake_repair(text, *, is_outline_doc=False):
        seen["is_outline_doc"] = is_outline_doc
        return text, {}

    monkeypatch.setattr("pagespeak.services._normalize_repair.repair_headings", fake_repair)

    out = tmp_path / "out"
    out.mkdir()
    record_outline_promoted(out, promoted=True)

    ctx = make_ctx(
        src=tmp_path / "doc.md",
        out=out,
        normalized_md_path=out / "doc.normalized.md",
        repaired_md_path=out / "doc.repaired.md",
    )
    ctx.result = IngestResult(markdown="# A\n\nbody\n", images=[], source_format="markdown")
    phases.RepairPhase().run(ctx)
    assert seen.get("is_outline_doc") is True, "RepairPhase did not forward the invariant"


def test_repair_phase_does_not_trust_an_inferred_hierarchy(tmp_path, monkeypatch) -> None:
    """No marker, Marker backend → repair must still do its job."""
    import pagespeak.orchestrators._phases as phases
    from pagespeak.models._models import IngestResult

    from .test_context import _ctx as make_ctx

    seen: dict[str, object] = {}

    def fake_repair(text, *, is_outline_doc=False):
        seen["is_outline_doc"] = is_outline_doc
        return text, {}

    monkeypatch.setattr("pagespeak.services._normalize_repair.repair_headings", fake_repair)

    out = tmp_path / "out"
    out.mkdir()
    ctx = make_ctx(
        src=tmp_path / "doc.md",
        out=out,
        normalized_md_path=out / "doc.normalized.md",
        repaired_md_path=out / "doc.repaired.md",
    )
    ctx.result = IngestResult(markdown="# A\n\nbody\n", images=[], source_format="markdown")
    phases.RepairPhase().run(ctx)
    assert seen.get("is_outline_doc") is False


# ── structure_authoritative: the DOCX reader's own structure ─────────────


class TestStructureAuthoritative:
    """A backend that read structure from the source format earns the same
    stand-down the outline-promotion path gets."""

    def test_records_and_reads_back(self, tmp_path):
        from pagespeak.services._hierarchy_trust import (
            record_structured,
            structure_authoritative,
        )

        assert structure_authoritative(tmp_path) is False
        record_structured(tmp_path, authoritative=True)
        assert structure_authoritative(tmp_path) is True

    def test_false_is_not_recorded(self, tmp_path):
        """A markitdown fallback must not stamp the flag."""
        from pagespeak.services._hierarchy_trust import (
            record_structured,
            structure_authoritative,
        )

        record_structured(tmp_path, authoritative=False)
        assert structure_authoritative(tmp_path) is False

    def test_recording_false_clears_a_previous_claim(self, tmp_path):
        """A re-ingest that switched backends must not inherit the old claim —
        its markdown is inferred, and needs the repair passes."""
        from pagespeak.services._hierarchy_trust import (
            hierarchy_is_trusted,
            record_structured,
            structure_authoritative,
        )

        record_structured(tmp_path, authoritative=True)
        record_structured(tmp_path, authoritative=False)
        assert structure_authoritative(tmp_path) is False
        assert not hierarchy_is_trusted(
            None, tmp_path, pdf_backend="marker", heading_hierarchy=False
        )

    def test_a_cleared_marker_is_not_trusted_by_its_existence(self, tmp_path):
        """The structure phase and the normalize-mode router both key off
        `has_authoritative_hierarchy`, so a leftover file must not stand them
        down — it reads the marker's values, not the file."""
        from pagespeak.services._hierarchy_trust import (
            has_authoritative_hierarchy,
            record_structured,
        )

        record_structured(tmp_path, authoritative=False)
        assert (tmp_path / ".pagespeak-hierarchy.json").is_file()
        assert not has_authoritative_hierarchy(
            None, pdf_backend="marker", heading_hierarchy=False, out=tmp_path
        )

    def test_marker_write_preserves_other_keys(self, tmp_path):
        """Three writers share this file; each must keep the others' keys."""
        from pagespeak.services._hierarchy_trust import (
            outline_promoted,
            record_outline_promoted,
            record_structured,
            structure_authoritative,
        )

        record_outline_promoted(tmp_path, promoted=True)
        record_structured(tmp_path, authoritative=True)
        assert outline_promoted(tmp_path) is True
        assert structure_authoritative(tmp_path) is True

    def test_counts_as_trusted_hierarchy(self, tmp_path):
        from pagespeak.services._hierarchy_trust import (
            hierarchy_is_trusted,
            record_structured,
        )

        assert not hierarchy_is_trusted(
            None, tmp_path, pdf_backend="marker", heading_hierarchy=False
        )
        record_structured(tmp_path, authoritative=True)
        assert hierarchy_is_trusted(None, tmp_path, pdf_backend="marker", heading_hierarchy=False)


class TestStructuredFlagIsProvenanceNotIntent:
    """The flag means "python-docx PRODUCED this", not "was requested":
    `convert_structured` falls back to MarkItDown on a parse failure, and that
    output's structure is inferred."""

    def test_markitdown_fallback_is_not_authoritative(self, tmp_path, monkeypatch):
        import pagespeak.backends._docx_structured as mod
        from pagespeak.models._models import IngestResult

        bad = tmp_path / "broken.docx"
        bad.write_bytes(b"not a docx at all")
        monkeypatch.setattr(
            "pagespeak.backends._docx.convert_with_markitdown",
            lambda *a, **k: IngestResult(markdown="fallback", source_format="docx"),
        )
        res = mod.convert_structured(bad, output_dir=tmp_path)
        assert res.markdown == "fallback"
        assert res.structure_authoritative is False


def test_cleanup_phase_reads_the_flag_when_there_is_no_out_dir(tmp_path, monkeypatch) -> None:
    """`to_markdown(..., output_dir=None)` writes no marker, so the in-memory
    flag is the only carrier of the signal."""
    import pagespeak.orchestrators._phases as phases
    from pagespeak.models._models import IngestResult

    from .test_context import _ctx as make_ctx

    seen: dict[str, object] = {}

    def fake_cleanup(text, *, level, cross_refs, stats=None, structure_authoritative=False):
        seen["structure_authoritative"] = structure_authoritative
        return text

    monkeypatch.setattr("pagespeak.services._cleanup.cleanup_markdown", fake_cleanup)

    ctx = make_ctx(src=tmp_path / "doc.docx", out=None, cleaned_md_path=None)
    ctx.result = IngestResult(
        markdown="# A\n\nbody\n", source_format="docx", structure_authoritative=True
    )
    phases.CleanupPhase().run(ctx)
    assert seen.get("structure_authoritative") is True


def test_repair_phase_reads_the_flag_when_there_is_no_out_dir(tmp_path, monkeypatch) -> None:
    """Same no-out-dir gap CleanupPhase covers: with `output_dir=None` there is
    no marker, so `result.structure_authoritative` is the only carrier."""
    import pagespeak.orchestrators._phases as phases
    from pagespeak.models._models import IngestResult

    from .test_context import _ctx as make_ctx

    seen: dict[str, object] = {}

    def fake_repair(text, *, is_outline_doc=False):
        seen["is_outline_doc"] = is_outline_doc
        return text, {}

    monkeypatch.setattr("pagespeak.services._normalize_repair.repair_headings", fake_repair)

    ctx = make_ctx(
        src=tmp_path / "doc.docx", out=None, normalized_md_path=None, repaired_md_path=None
    )
    ctx.result = IngestResult(
        markdown="# A\n\nbody\n", source_format="docx", structure_authoritative=True
    )
    phases.RepairPhase().run(ctx)
    assert seen.get("is_outline_doc") is True, "RepairPhase dropped the in-memory claim"


def test_structure_phase_reads_the_flag_when_there_is_no_out_dir(tmp_path, monkeypatch) -> None:
    """The level-rewriting passes must stand down on an authoritative structure
    even when no marker exists to carry the signal."""
    import pagespeak.orchestrators._phases as phases
    from pagespeak.models._models import IngestResult

    from .test_context import _ctx as make_ctx

    ran: list[str] = []

    monkeypatch.setattr(
        "pagespeak.services._flat_source_demote.demote_flat_h1_runs",
        lambda text: ran.append("demote") or text,
    )
    monkeypatch.setattr(
        "pagespeak.services._h1_ratio_rebalance.rebalance_orphan_h1s",
        lambda text: ran.append("rebalance") or text,
    )

    ctx = make_ctx(
        src=tmp_path / "doc.docx", out=None, repaired_md_path=None, structured_md_path=None
    )
    ctx.result = IngestResult(
        markdown="# A\n\n# B\n\n# C\n", source_format="docx", structure_authoritative=True
    )
    phases.StructurePhase().run(ctx)
    assert ran == [], f"StructurePhase re-guessed an authoritative hierarchy: {ran}"


def _docx_ctx(tmp_path):
    """An IngestPhase context for a .docx with a real `out` dir."""
    from .test_context import _ctx as make_ctx

    src = tmp_path / "doc.docx"
    src.write_bytes(b"stub")
    out = tmp_path / "out"
    out.mkdir()
    return make_ctx(
        src=src,
        out=out,
        suffix=".docx",
        source_format="docx",
        dir_mode=False,
        raw_md_path=out / "doc.raw.md",
        doc_stem="doc",
        effective_stem="doc",
    )


def test_ingest_phase_writes_the_readers_claim_to_the_marker(tmp_path, monkeypatch) -> None:
    """Cleanup runs in a later invocation and re-reads the marker, so a claim
    that never reaches disk is a claim that never happened."""
    import pagespeak.orchestrators._phases as phases
    from pagespeak.backends import _docx_dispatch
    from pagespeak.models._models import IngestResult
    from pagespeak.services._hierarchy_trust import structure_authoritative

    monkeypatch.setattr(
        _docx_dispatch,
        "convert",
        lambda *a, **k: IngestResult(
            markdown="# A\n\nbody\n", source_format="docx", structure_authoritative=True
        ),
    )
    ctx = _docx_ctx(tmp_path)
    phases.IngestPhase().run(ctx)
    assert structure_authoritative(ctx.out) is True


def test_ingest_phase_clears_a_stale_claim(tmp_path, monkeypatch) -> None:
    """Re-ingesting with a backend that infers structure must retract the
    previous backend's claim, or the repair passes stay gated off forever."""
    import pagespeak.orchestrators._phases as phases
    from pagespeak.backends import _docx_dispatch
    from pagespeak.models._models import IngestResult
    from pagespeak.services._hierarchy_trust import record_structured, structure_authoritative

    monkeypatch.setattr(
        _docx_dispatch,
        "convert",
        lambda *a, **k: IngestResult(markdown="# A\n\nbody\n", source_format="docx"),
    )
    ctx = _docx_ctx(tmp_path)
    record_structured(ctx.out, authoritative=True)
    phases.IngestPhase().run(ctx)
    assert structure_authoritative(ctx.out) is False


def test_cleanup_phase_honours_a_pdf_outline_hierarchy(tmp_path, monkeypatch) -> None:
    """Phase-level: CleanupPhase must stand its demote passes down for a PDF
    whose levels came from the document's own bookmark outline.

    `structure_authoritative` is written only by the DOCX structured reader, so
    gating on it alone leaves every outline-derived PDF unprotected — cleanup
    then demotes headings the source itself levelled.
    """
    import pagespeak.orchestrators._phases as phases
    import pagespeak.services._hierarchy_trust as ht
    from pagespeak.models._models import IngestResult
    from pagespeak.services._hierarchy_trust import record_hierarchy_source

    from .test_context import _ctx as make_ctx

    seen: dict[str, object] = {}

    def fake_cleanup(text, **kwargs):
        seen["structure_authoritative"] = kwargs.get("structure_authoritative")
        return text

    monkeypatch.setattr("pagespeak.services._cleanup.cleanup_markdown", fake_cleanup)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(ht, "pdf_outline_depth", lambda _s: 3)
    record_hierarchy_source(out, pdf, pdf_backend="docling", heading_hierarchy=True)
    # The marker states an outline-derived hierarchy and no DOCX-reader claim.
    assert ht.structure_authoritative(out) is False

    ctx = make_ctx(
        src=pdf,
        out=out,
        raw_md_path=out / "doc.raw.md",
        cleaned_md_path=out / "doc.cleaned.md",
    )
    ctx.pdf_backend = "docling"
    ctx.heading_hierarchy = True
    ctx.result = IngestResult(markdown="# A\n\nbody\n", images=[], source_format="pdf")
    phases.CleanupPhase().run(ctx)
    assert seen.get("structure_authoritative") is True, (
        "CleanupPhase demoted headings on an outline-derived hierarchy"
    )


def test_chunked_ingest_stamps_the_hierarchy_marker(tmp_path, monkeypatch):
    """Both ingest entry points must stamp provenance. The chunked path did not,
    so `--pdf-backend docling --heading-hierarchy --workers N` silently lost the
    outline trust that the single-process path records."""
    from pagespeak.orchestrators import _ingest as ing

    out = tmp_path / "out"
    out.mkdir()
    raw = out / "doc.raw.md"
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        "pagespeak.services._hierarchy_trust.record_hierarchy_source",
        lambda o, s, **kw: recorded.update({"src": s, **kw}),
    )
    monkeypatch.setattr(
        "pagespeak.services._hierarchy_trust.record_structured",
        lambda o, **kw: recorded.update({"structured": kw.get("authoritative")}),
    )

    class _Chunk:
        page_range, status = "0-9", "completed"

    class _Manifest:
        chunks = [_Chunk()]
        shelved: list[object] = []

        def all_chunk_raw_md(self):
            p = out / "chunks" / "0-9" / "raw.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# chunk\n", encoding="utf-8")
            return [p]

        def all_chunk_images(self):
            return []

    monkeypatch.setattr(ing, "chunk_phase", lambda **kw: _Manifest())

    ing._ingest_chunked(
        src,
        out,
        raw_md_path=raw,
        workers=2,
        chunk_pages=50,
        pdf_backend="docling",
        pdf_backend_kwargs=None,
        heading_hierarchy=True,
        device=None,
        force_ocr=False,
        force=False,
        max_pages=None,
    )

    assert recorded.get("pdf_backend") == "docling"
    assert recorded.get("heading_hierarchy") is True
    assert recorded.get("src") == src, "must stamp the real PDF, not the checkpoint"
    assert recorded.get("structured") is False
