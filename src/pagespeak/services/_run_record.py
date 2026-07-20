"""Write `<output_dir>/.pagespeak-run.json` after every successful run.

Thin shim over `pf_core.pipeline.run_record`. The run record captures the
resolved configuration that produced the output — preset name (if any),
every flag value the pipeline saw, the input file's SHA-256, and
timestamps. Makes re-run drift diagnosable: a one-line diff
between two `.pagespeak-run.json` files shows exactly what config
differs.

It also includes an `llm_calls` per-task summary aggregated from the
per-call summaries drained out of pf-core's recording window
(`pf_core.llm.recording`, re-exported by `_agent_runtime`). The schema is
documented in `docs/presets.md` § "Re-run reproducibility".

Binds the pagespeak-specific filename (`.pagespeak-run.json`) and
preserves the public API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pf_core.pipeline.run_record import file_sha256
from pf_core.pipeline.run_record import read_run_record as _read_run_record
from pf_core.pipeline.run_record import write_run_record as _write_run_record

__all__ = [
    "RUN_RECORD_FILENAME",
    "file_sha256",
    "read_run_record",
    "summarize_llm_calls",
    "write_run_record",
]

RUN_RECORD_FILENAME = ".pagespeak-run.json"


def read_run_record(output_dir: Path) -> dict[str, Any] | None:
    """Read `<output_dir>/.pagespeak-run.json` defensively.

    Returns None when the file is missing, unreadable, malformed JSON, or
    not a JSON object — a bad record must never break the consumers that
    merely *prefer* it (provenance recovery, re-run flag inheritance)."""
    try:
        record = _read_run_record(output_dir, filename=RUN_RECORD_FILENAME)
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def summarize_llm_calls(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate pf-core recording-window summaries (`agent_type` /
    `provider` / usage fields) into the per-task `by_task` summary stored
    in ``.pagespeak-run.json``.

    Empty `records` returns a zero-valued summary with empty `by_task`.
    """
    summary: dict[str, Any] = {
        "total_calls": len(records),
        "successful": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_cost_usd": 0.0,
        "total_duration_ms": 0,
        "by_task": {},
    }
    by_task: dict[str, dict[str, Any]] = summary["by_task"]
    models_seen: dict[str, set[str]] = {}
    backends_seen: dict[str, set[str]] = {}

    for r in records:
        success = bool(r.get("success"))
        prompt_tokens = int(r.get("prompt_tokens", 0))
        completion_tokens = int(r.get("completion_tokens", 0))
        cost_usd = float(r.get("cost_usd", 0.0))
        duration_ms = int(r.get("duration_ms", 0))
        task = str(r.get("agent_type") or "unknown")
        model = str(r.get("model", ""))
        backend = str(r.get("provider") or "")

        summary["successful"] += int(success)
        summary["total_prompt_tokens"] += prompt_tokens
        summary["total_completion_tokens"] += completion_tokens
        summary["total_cost_usd"] += cost_usd
        summary["total_duration_ms"] += duration_ms

        bucket = by_task.setdefault(
            task,
            {
                "calls": 0,
                "successful": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
                "duration_ms": 0,
                "models_used": [],
                "backends_used": [],
            },
        )
        bucket["calls"] += 1
        bucket["successful"] += int(success)
        bucket["prompt_tokens"] += prompt_tokens
        bucket["completion_tokens"] += completion_tokens
        bucket["cost_usd"] += cost_usd
        bucket["duration_ms"] += duration_ms

        models_seen.setdefault(task, set()).add(model)
        backends_seen.setdefault(task, set()).add(backend)

    # Fold the de-duped sets back into the bucket dicts as sorted lists
    # so the JSON output is stable and human-readable.
    for task, bucket in by_task.items():
        bucket["models_used"] = sorted(m for m in models_seen.get(task, set()) if m)
        bucket["backends_used"] = sorted(b for b in backends_seen.get(task, set()) if b)

    return summary


def write_run_record(
    output_dir: Path,
    *,
    version: str,
    preset: str | None,
    resolved_flags: dict[str, Any],
    input_path: Path,
    started_at: str,
    finished_at: str,
    section_count: int | None,
    image_count: int,
    llm_calls: dict[str, Any] | None = None,
    source_identity: dict[str, Any] | None = None,
) -> Path:
    """Write `<output_dir>/.pagespeak-run.json`. Returns the written path.

    `llm_calls` is the aggregated per-task LLM call summary
    produced by :func:`summarize_llm_calls`. `source_identity` is the durable
    original-source block from `_provenance.persistable_source_identity`
    (dir-mode re-runs carry it forward). Pass ``None`` (default) to omit
    either field entirely.
    """
    fields: dict[str, Any] = {}
    if llm_calls is not None:
        fields["llm_calls"] = llm_calls
    if source_identity is not None:
        fields["source_identity"] = source_identity
    extra: dict[str, Any] | None = fields or None
    written: Path = _write_run_record(
        output_dir,
        version=version,
        preset=preset,
        resolved_flags=resolved_flags,
        input_path=input_path,
        started_at=started_at,
        finished_at=finished_at,
        section_count=section_count,
        image_count=image_count,
        extra=extra,
        filename=RUN_RECORD_FILENAME,
    )
    return written
