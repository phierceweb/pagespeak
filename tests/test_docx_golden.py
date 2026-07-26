"""Golden test for the structure-faithful DOCX reader.

Covers the constructs python-docx will not write and no other test can produce
a `.docx` containing — tracked insertions, OMML, content controls, fields,
tab-separated runs, sub/superscript runs.

The fixture is generated (`tests/fixtures/structured_docx.py`) rather than
committed as a binary, so a reviewer can see which shape changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("docx", reason="needs the docx-structured extra")

from pagespeak.backends._docx_structured import convert_structured  # noqa: E402
from pagespeak.services._cleanup import cleanup_markdown  # noqa: E402

from .fixtures.structured_docx import build_structured_docx  # noqa: E402

_EXPECTED = Path(__file__).parent / "fixtures" / "structured_docx_expected.md"


@pytest.fixture
def golden(tmp_path: Path):
    src = build_structured_docx(tmp_path / "golden.docx")
    return convert_structured(src, output_dir=tmp_path / "out", outline_heading_depth=0)


def test_reader_output_matches_golden(golden) -> None:
    """Byte-for-byte against the committed expectation.

    Regenerate deliberately (and read the diff) when the reader's contract
    changes — never to make a red test green.
    """
    assert golden.markdown == _EXPECTED.read_text(encoding="utf-8")


def test_structure_authoritative_is_set(golden) -> None:
    assert golden.structure_authoritative is True


class TestRunContainersAreNotDropped:
    """Asserted individually so a failure names the container, not just a
    golden mismatch."""

    @pytest.mark.parametrize(
        "text,container",
        [
            ("Inserted clause retained.", "w:ins (tracked insertion)"),
            ("Content control text.", "w:sdt"),
            ("Field text.", "w:fldSimple"),
            ("Smart tag text.", "w:smartTag"),
            ("E = mc^2", "m:oMath"),
        ],
    )
    def test_container_text_survives(self, golden, text: str, container: str) -> None:
        assert text in golden.markdown, f"{container} content was dropped"


class TestRunJoining:
    def test_subscript_and_superscript_do_not_shatter(self, golden) -> None:
        """The `**CO****2****` shape: emphasis marks re-opened per run."""
        assert "CO2" in golden.markdown
        assert "m3" in golden.markdown
        assert "****" not in golden.markdown

    def test_tab_between_runs_does_not_fuse_words(self, golden) -> None:
        assert "Torquesetting" not in golden.markdown
        assert "Torque setting" in golden.markdown


class TestCleanupDoesNotDestroyReadStructure:
    """The golden above would still pass with the trust signal deleted; these
    assert the difference the signal makes."""

    def _headings(self, md: str) -> set[str]:
        return {ln.lstrip("#").strip() for ln in md.splitlines() if ln.startswith("#")}

    def test_authored_heading_survives_cleanup(self, tmp_path: Path) -> None:
        """`Connector types` is a genuine Word `Heading 2`; cleanup deletes it
        without the signal."""
        src = build_structured_docx(tmp_path / "g.docx")
        res = convert_structured(src, output_dir=tmp_path / "o", outline_heading_depth=2)
        without = self._headings(cleanup_markdown(res.markdown, level="basic"))
        with_signal = self._headings(
            cleanup_markdown(res.markdown, level="basic", structure_authoritative=True)
        )
        assert "Connector types" not in without, (
            "fixture no longer reproduces the bug — it cannot detect a regression"
        )
        assert "Connector types" in with_signal

    def test_signal_preserves_every_read_heading(self, tmp_path: Path) -> None:
        src = build_structured_docx(tmp_path / "g.docx")
        res = convert_structured(src, output_dir=tmp_path / "o", outline_heading_depth=2)
        read = self._headings(res.markdown)
        kept = self._headings(
            cleanup_markdown(res.markdown, level="basic", structure_authoritative=True)
        )
        assert read <= kept, f"cleanup dropped: {sorted(read - kept)}"


def test_numbering_restarts_after_a_heading_styled_section(golden) -> None:
    """A Word `Heading N` paragraph starts a new section, so its list restarts.

    Named separately from the golden comparison so the intent survives a
    future regeneration.
    """
    body = golden.markdown.split("## Connector types", 1)[1]
    first_item = next(ln for ln in body.splitlines() if ln.strip() and ln.strip()[0].isdigit())
    assert first_item.strip().startswith("1."), (
        f"list under a heading did not restart numbering: {first_item!r}"
    )
