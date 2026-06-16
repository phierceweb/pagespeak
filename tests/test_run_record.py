"""Binding test for `pagespeak.services._run_record`.

The substantive behavior (file_sha256, run-record schema, atomic write,
streaming-hash correctness) is exercised in pf-core's
`test_pipeline_run_record.py`. This module pins the pagespeak-specific
binding only: `RUN_RECORD_FILENAME == ".pagespeak-run.json"` is what
the shim passes through to pf-core, and `write_run_record` writes to
that exact name.
"""

from __future__ import annotations

from pathlib import Path

from pagespeak.services._run_record import (
    RUN_RECORD_FILENAME,
    write_run_record,
)


def test_run_record_filename_is_pagespeak_specific() -> None:
    """Pagespeak's hidden-file convention. Changing this breaks
    downstream baseline/diff/resume code that hardcodes the name."""
    assert RUN_RECORD_FILENAME == ".pagespeak-run.json"


def test_write_run_record_uses_pagespeak_filename(tmp_path: Path) -> None:
    """The shim must write to `.pagespeak-run.json`, not pf-core's default."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"fake pdf bytes")
    out = tmp_path / "out"
    out.mkdir()
    written = write_run_record(
        out,
        version="0.1.0",
        preset=None,
        resolved_flags={"cleanup": "basic"},
        input_path=src,
        started_at="2026-05-10T00:00:00Z",
        finished_at="2026-05-10T00:00:30Z",
        section_count=42,
        image_count=7,
    )
    assert written == out / RUN_RECORD_FILENAME
    assert written.exists()


# --- llm_calls summary -------------------------------------------


def test_summarize_llm_calls_empty_records_returns_zero_summary() -> None:
    from pagespeak.services._run_record import summarize_llm_calls

    summary = summarize_llm_calls([])
    assert summary["total_calls"] == 0
    assert summary["successful"] == 0
    assert summary["total_cost_usd"] == 0.0
    assert summary["by_task"] == {}


def test_summarize_llm_calls_aggregates_per_task() -> None:
    """Multi-task records produce per-task buckets with dedup'd
    models_used / backends_used lists."""
    from pagespeak.services._run_record import summarize_llm_calls

    records = [
        {
            "task": "vision",
            "backend": "claude_code",
            "model": "claude-haiku-4-5-20251001",
            "prompt_version": 2,
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "cost_usd": 0.01,
            "duration_ms": 500,
            "success": True,
            "run_id": 1,
        },
        {
            "task": "vision",
            "backend": "claude_code",
            "model": "claude-haiku-4-5-20251001",
            "prompt_version": 2,
            "prompt_tokens": 150,
            "completion_tokens": 250,
            "cost_usd": 0.02,
            "duration_ms": 600,
            "success": True,
            "run_id": 2,
        },
        {
            "task": "heading_normalize_full",
            "backend": "openrouter",
            "model": "google/gemini-2.5-flash",
            "prompt_version": 1,
            "prompt_tokens": 5000,
            "completion_tokens": 800,
            "cost_usd": 0.05,
            "duration_ms": 12000,
            "success": True,
            "run_id": 3,
        },
    ]
    summary = summarize_llm_calls(records)
    assert summary["total_calls"] == 3
    assert summary["successful"] == 3
    assert summary["total_prompt_tokens"] == 5250
    assert summary["total_completion_tokens"] == 1250
    assert abs(summary["total_cost_usd"] - 0.08) < 1e-9
    assert summary["total_duration_ms"] == 13100

    vision = summary["by_task"]["vision"]
    assert vision["calls"] == 2
    assert vision["successful"] == 2
    assert vision["prompt_tokens"] == 250
    assert vision["completion_tokens"] == 450
    assert vision["models_used"] == ["claude-haiku-4-5-20251001"]
    assert vision["backends_used"] == ["claude_code"]

    hn_full = summary["by_task"]["heading_normalize_full"]
    assert hn_full["calls"] == 1
    assert hn_full["models_used"] == ["google/gemini-2.5-flash"]
    assert hn_full["backends_used"] == ["openrouter"]


def test_summarize_llm_calls_dedups_models_and_backends_per_task() -> None:
    """When the same task is called with multiple models/backends in
    one conversion, both are listed (sorted, deduped)."""
    from pagespeak.services._run_record import summarize_llm_calls

    records = [
        {
            "task": "vision",
            "backend": "claude_code",
            "model": "claude-haiku-4-5-20251001",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "duration_ms": 0,
            "success": True,
        },
        {
            "task": "vision",
            "backend": "openrouter",
            "model": "google/gemini-2.5-flash",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "duration_ms": 0,
            "success": True,
        },
    ]
    summary = summarize_llm_calls(records)
    vision = summary["by_task"]["vision"]
    assert vision["models_used"] == [
        "claude-haiku-4-5-20251001",
        "google/gemini-2.5-flash",
    ]
    assert vision["backends_used"] == ["claude_code", "openrouter"]


def test_run_record_writes_llm_calls_when_provided(tmp_path: Path) -> None:
    """When `llm_calls=` is supplied to write_run_record, the JSON
    output carries the field as a top-level key."""
    import json

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"fake pdf bytes")
    out = tmp_path / "out"
    out.mkdir()

    llm_calls = {
        "total_calls": 5,
        "successful": 5,
        "total_cost_usd": 0.123,
        "by_task": {"vision": {"calls": 5, "models_used": ["x"]}},
    }
    written = write_run_record(
        out,
        version="0.1.0",
        preset=None,
        resolved_flags={},
        input_path=src,
        started_at="2026-05-12T00:00:00Z",
        finished_at="2026-05-12T00:00:30Z",
        section_count=None,
        image_count=0,
        llm_calls=llm_calls,
    )
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["llm_calls"] == llm_calls


def test_run_record_omits_llm_calls_when_not_provided(tmp_path: Path) -> None:
    """When `llm_calls=` is None (default / library backward-compat),
    the field is absent from the JSON."""
    import json

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"fake pdf bytes")
    out = tmp_path / "out"
    out.mkdir()

    written = write_run_record(
        out,
        version="0.1.0",
        preset=None,
        resolved_flags={},
        input_path=src,
        started_at="2026-05-12T00:00:00Z",
        finished_at="2026-05-12T00:00:30Z",
        section_count=None,
        image_count=0,
    )
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "llm_calls" not in data
