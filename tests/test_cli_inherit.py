"""Tests for `pagespeak.cli._inherit` — run-record flag inheritance.

When `pagespeak convert` targets an existing output dir holding a
`.pagespeak-run.json`, flags not explicitly passed on the command line
default to the record's `resolved_flags`. Explicit CLI flags win;
`--no-inherit` disables the mechanism; LLM/engine/runtime flags are
never inherited (a re-run must not let history select a backend).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from pagespeak.cli import app
from pagespeak.cli._inherit import (
    _FLAG_TYPES,
    _PRESET_CONTROLLED_FLAGS,
    INHERITABLE_FLAGS,
    apply_run_record_defaults,
    inherited_updates,
)
from pagespeak.services._run_record import RUN_RECORD_FILENAME

runner = CliRunner()


# --- inherited_updates (pure merge) -------------------------------


def test_inherited_updates_picks_nonexplicit_record_values() -> None:
    flags = {
        "split_sections": True,
        "nested_split": True,
        "split_min_level": 2,
        "cleanup": "aggressive",
    }
    updates, warnings = inherited_updates(
        {"resolved_flags": flags}, explicit=set(), preset_explicit=False
    )
    assert updates == flags
    assert warnings == []


def test_inherited_updates_explicit_flags_excluded() -> None:
    updates, _ = inherited_updates(
        {"resolved_flags": {"split_sections": True, "cleanup": "off"}},
        explicit={"split_sections"},
        preset_explicit=False,
    )
    assert "split_sections" not in updates
    assert updates["cleanup"] == "off"


def test_inherited_updates_preset_excludes_preset_controlled_only() -> None:
    """An explicit --preset supplies the preset-controlled flags, so those
    must not inherit; every other recorded flag still does."""
    flags = {"split_sections": True, "split_target_kb": 32, "source_label": "Guide"}
    updates, _ = inherited_updates({"resolved_flags": flags}, explicit=set(), preset_explicit=True)
    assert "split_sections" not in updates
    assert updates["split_target_kb"] == 32
    assert updates["source_label"] == "Guide"


def test_inherited_updates_skips_none_values() -> None:
    updates, warnings = inherited_updates(
        {"resolved_flags": {"split_max_level": None, "source_type": None}},
        explicit=set(),
        preset_explicit=False,
    )
    assert updates == {}
    assert warnings == []


def test_inherited_updates_skips_type_mismatches_with_warning() -> None:
    """Hand-edited or drifted records: wrong-typed values are skipped, each
    with a warning naming the flag. bool is not accepted for int flags."""
    flags = {"split_sections": "yes", "split_min_level": True, "page_range": [0, 1]}
    updates, warnings = inherited_updates(
        {"resolved_flags": flags}, explicit=set(), preset_explicit=False
    )
    assert updates == {}
    assert len(warnings) == 3
    assert any("split_sections" in w for w in warnings)
    assert any("split_min_level" in w for w in warnings)
    assert any("page_range" in w for w in warnings)


def test_inherited_updates_never_inherits_llm_or_runtime_flags() -> None:
    """Cost/runtime axis: engine selection, model choice, vision gating and
    machine-specific flags must never be taken from history."""
    flags = {
        "diagrams": False,
        "vision_backend": "anthropic",
        "vision_model": "some-model",
        "vision_concurrency": 2,
        "vision_cache_only": True,
        "preserve_alt": True,
        "normalize_headings_model": "some-model",
        "device": "cuda",
        "split_sections": True,
    }
    updates, warnings = inherited_updates(
        {"resolved_flags": flags}, explicit=set(), preset_explicit=False
    )
    assert updates == {"split_sections": True}
    assert warnings == []


def test_inherited_updates_handles_missing_or_malformed_resolved_flags() -> None:
    for record in ({}, {"resolved_flags": None}, {"resolved_flags": ["not", "a", "dict"]}):
        updates, warnings = inherited_updates(record, explicit=set(), preset_explicit=False)
        assert updates == {}
        assert warnings == []


def test_every_inheritable_flag_has_a_type_spec() -> None:
    """Adding a flag to one table but not the other is a silent hole."""
    assert set(INHERITABLE_FLAGS) == set(_FLAG_TYPES)
    assert set(_PRESET_CONTROLLED_FLAGS) <= set(INHERITABLE_FLAGS)


# --- apply_run_record_defaults (record IO + notice + validation) ---


def test_apply_returns_empty_when_no_record(tmp_path: Path) -> None:
    echoed: list[str] = []
    updates = apply_run_record_defaults(
        output_dir=tmp_path, explicit=set(), validators={}, echo=echoed.append
    )
    assert updates == {}
    assert echoed == []


def test_apply_corrupt_record_returns_empty(tmp_path: Path) -> None:
    (tmp_path / RUN_RECORD_FILENAME).write_text("{not json", encoding="utf-8")
    echoed: list[str] = []
    updates = apply_run_record_defaults(
        output_dir=tmp_path, explicit=set(), validators={}, echo=echoed.append
    )
    assert updates == {}
    assert echoed == []


def test_apply_echoes_notice_naming_record_and_escape(tmp_path: Path, make_run_record) -> None:
    make_run_record(tmp_path, {"split_sections": True, "split_min_level": 2})
    echoed: list[str] = []
    updates = apply_run_record_defaults(
        output_dir=tmp_path, explicit=set(), validators={}, echo=echoed.append
    )
    assert updates == {"split_sections": True, "split_min_level": 2}
    assert len(echoed) == 1
    msg = echoed[0]
    assert RUN_RECORD_FILENAME in msg
    assert "split_sections=True" in msg
    assert "--no-inherit" in msg


def test_apply_silent_when_nothing_inherited(tmp_path: Path, make_run_record) -> None:
    make_run_record(tmp_path, {"split_sections": True})
    echoed: list[str] = []
    updates = apply_run_record_defaults(
        output_dir=tmp_path,
        explicit={"split_sections"},
        validators={},
        echo=echoed.append,
    )
    assert updates == {}
    assert echoed == []


def test_apply_runs_validator_on_inherited_value(tmp_path: Path, make_run_record) -> None:
    make_run_record(tmp_path, {"cleanup": "aggressive"})
    seen: list[str] = []

    def _validate(value: str) -> str:
        seen.append(value)
        return value

    updates = apply_run_record_defaults(
        output_dir=tmp_path,
        explicit=set(),
        validators={"cleanup": _validate},
        echo=lambda s: None,
    )
    assert updates["cleanup"] == "aggressive"
    assert seen == ["aggressive"]


def test_apply_invalid_enum_value_fails_naming_record(tmp_path: Path, make_run_record) -> None:
    """A recorded value the validators reject must fail loudly, telling the
    user where the bad value came from and how to bypass it."""
    make_run_record(tmp_path, {"cleanup": "bogus"})

    def _validate(value: str) -> str:
        raise typer.BadParameter(f"bad cleanup {value!r}")

    with pytest.raises(typer.BadParameter) as exc_info:
        apply_run_record_defaults(
            output_dir=tmp_path,
            explicit=set(),
            validators={"cleanup": _validate},
            echo=lambda s: None,
        )
    message = str(exc_info.value.message)
    assert RUN_RECORD_FILENAME in message
    assert "--no-inherit" in message


# --- CLI wiring (convert picks up the record) ----------------------


def _capture_to_markdown(monkeypatch) -> dict[str, object]:
    from pagespeak.cli import _convert
    from pagespeak.models._models import IngestResult

    captured: dict[str, object] = {}

    def fake_to_markdown(path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return IngestResult(markdown="# Doc\n", images=[], diagrams=[], source_format="raw")

    monkeypatch.setattr(_convert, "to_markdown", fake_to_markdown)
    return captured


def _recorded_out_dir(tmp_path: Path, make_run_record, flags: dict) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("# Doc\n", encoding="utf-8")
    make_run_record(out, flags)
    return out


def test_convert_dir_mode_inherits_recorded_flags(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    captured = _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(
        tmp_path,
        make_run_record,
        {
            "split_sections": True,
            "nested_split": True,
            "split_min_level": 2,
            "cleanup": "aggressive",
            "english_only": True,
            "min_body_chars": 99,
            "regenerate_toc": False,
            "source_label": "Guide",
        },
    )
    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is True
    assert captured["nested_split"] is True
    assert captured["split_min_level"] == 2
    assert captured["cleanup"] == "aggressive"
    assert captured["english_only"] is True
    assert captured["min_body_chars"] == 99
    assert captured["regenerate_toc"] is False
    assert captured["source_label"] == "Guide"


def test_convert_explicit_flag_beats_record(tmp_path: Path, monkeypatch, make_run_record) -> None:
    captured = _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(
        tmp_path, make_run_record, {"split_sections": True, "cleanup": "aggressive"}
    )
    result = runner.invoke(app, ["convert", str(out), "--no-split-sections", "--cleanup", "basic"])
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is False
    assert captured["cleanup"] == "basic"


def test_convert_no_inherit_restores_bare_defaults(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    captured = _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(
        tmp_path,
        make_run_record,
        {"split_sections": True, "english_only": True, "cleanup": "aggressive"},
    )
    result = runner.invoke(app, ["convert", str(out), "--no-inherit"])
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is None
    assert captured["english_only"] is False
    assert captured["cleanup"] is None


def test_convert_explicit_preset_beats_record_for_preset_flags(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    """--preset on the re-run re-shapes the preset-controlled flags (library
    resolves them from the preset); non-preset flags still inherit."""
    captured = _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(
        tmp_path, make_run_record, {"split_min_level": 3, "split_target_kb": 48}
    )
    result = runner.invoke(app, ["convert", str(out), "--preset", "flat"])
    assert result.exit_code == 0, result.output
    assert captured["preset"] == "flat"
    assert captured["split_min_level"] is None
    assert captured["split_target_kb"] == 48


def test_convert_never_inherits_vision_flags(tmp_path: Path, monkeypatch, make_run_record) -> None:
    """Cost-safety pin: a record must never re-select an LLM engine/model,
    flip the vision pass, or carry a machine-specific device."""
    captured = _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(
        tmp_path,
        make_run_record,
        {
            "diagrams": False,
            "vision_backend": "anthropic",
            "vision_model": "some-model",
            "vision_cache_only": True,
            "preserve_alt": True,
            "device": "cuda",
        },
    )
    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["diagrams"] is True
    assert captured["vision_backend"] is None
    assert captured["vision_model"] is None
    assert captured["vision_cache_only"] is False
    assert captured["preserve_alt"] is False
    assert captured["device"] is None


def test_convert_corrupt_record_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    captured = _capture_to_markdown(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.raw.md").write_text("# Doc\n", encoding="utf-8")
    (out / RUN_RECORD_FILENAME).write_text("{broken json", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is None


def test_convert_invalid_record_enum_fails_loud(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(tmp_path, make_run_record, {"cleanup": "bogus"})
    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code != 0
    assert RUN_RECORD_FILENAME in result.output


def test_convert_notice_line_lists_inherited_flags(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    _capture_to_markdown(monkeypatch)
    out = _recorded_out_dir(tmp_path, make_run_record, {"split_sections": True})
    result = runner.invoke(app, ["convert", str(out)])
    assert result.exit_code == 0, result.output
    assert RUN_RECORD_FILENAME in result.output
    assert "split_sections=True" in result.output


def test_convert_file_mode_with_recorded_outdir_inherits(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    """Not just dir-mode: `convert doc.md -o <recorded dir>` also inherits."""
    captured = _capture_to_markdown(monkeypatch)
    out = tmp_path / "out"
    make_run_record(out, {"split_sections": True, "nested_split": True})
    src = tmp_path / "doc.md"
    src.write_text("# Doc\n\nbody\n", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is True
    assert captured["nested_split"] is True


def test_convert_qti_export_dir_never_inherits(
    tmp_path: Path, monkeypatch, make_run_record
) -> None:
    """A QTI export is a SOURCE directory; a stray record in the target
    output dir must not feed flag inheritance."""
    captured = _capture_to_markdown(monkeypatch)
    src = tmp_path / "export"
    src.mkdir()
    (src / "imsmanifest.xml").write_text("<manifest/>", encoding="utf-8")
    out = tmp_path / "qti-out"
    make_run_record(out, {"split_sections": True})
    result = runner.invoke(app, ["convert", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert captured["split_sections"] is None
