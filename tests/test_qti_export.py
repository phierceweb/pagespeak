"""Tests for orchestrators._qti_export."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pagespeak.models._models import IngestResult


@pytest.mark.parametrize("all_images", [False, True])
def test_vision_flags_reach_each_exam(tmp_path: Path, monkeypatch, all_images: bool) -> None:
    import pagespeak
    from pagespeak.orchestrators import _qti_export

    exam = SimpleNamespace(title="Exam 1", quiz_id="q1", points_possible=1)
    export = SimpleNamespace(exams=[exam], course="Course", is_temp=False, root=tmp_path)
    monkeypatch.setattr(_qti_export, "enumerate_quizzes", lambda src: export)
    monkeypatch.setattr(
        _qti_export,
        "convert_qti_exam",
        lambda _exam, _export, exam_dir, **_: exam_dir.mkdir(parents=True),
    )
    seen: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        seen.update(kwargs)
        return IngestResult(markdown="## Question 1\n\nWhat?\n", images=[], source_format="raw")

    monkeypatch.setattr(pagespeak, "to_markdown", fake_to_markdown)
    _qti_export.run_qti_export(
        tmp_path / "export",
        tmp_path / "out",
        diagrams=True,
        cleanup="basic",
        vision_backend=None,
        vision_model=None,
        vision_concurrency=None,
        vision_cache_only=False,
        vision_all_images=all_images,
        source_type=None,
        source_label=None,
        answer_key=True,
    )
    assert seen["vision_all_images"] is all_images
