"""In-process conversion worker.

One job = one ``pagespeak convert`` subprocess covering the job's phase
slice, run with ``PAGESPEAK_JOB_ID`` set so LLM rows attribute to the job.
Progress is read from on-disk checkpoints by the scanner. The runtime —
claim loop, subprocess lifecycle, cancel with SIGKILL escalation,
stale-lease reclaim at startup — is ``pf_core.jobs.workers``; this module
supplies the conversion-domain :class:`SubprocessJobSpec`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pf_core.jobs.workers import (  # noqa: F401 — re-exports for web/__init__ + actions
    SubprocessJobSpec,
    WorkerHandle,
    run_subprocess_job,
    stop_workers,
    terminate_job,
)
from pf_core.jobs.workers import start_workers as _pf_start_workers

from pagespeak.web._command import build_command, log_path, resolve_pagespeak_bin
from pagespeak.web._config import WebConfig
from pagespeak.web._jobs import (
    CONVERSION_KIND,
    ConversionInputs,
    ConversionOutputs,
    register_conversion_kind,
)

__all__ = [
    "SPEC",
    "WorkerHandle",
    "run_job",
    "start_workers",
    "stop_workers",
    "terminate_job",
]


def _inputs(job_row: dict[str, Any]) -> ConversionInputs:
    return ConversionInputs.model_validate(job_row["inputs"] or {})


def _argv(job_row: dict[str, Any]) -> list[str]:
    return build_command(_inputs(job_row), pagespeak_bin=resolve_pagespeak_bin())


def _log_path(job_row: dict[str, Any]) -> Path:
    out_dir = Path(_inputs(job_row).out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return log_path(out_dir, int(job_row["id"]))


def _outputs(job_row: dict[str, Any], rc: int) -> ConversionOutputs:
    inp = _inputs(job_row)
    return ConversionOutputs(
        phases=f"{inp.start or 'ingest'}..{inp.stop_after or 'split'}",
        returncode=rc,
    )


SPEC = SubprocessJobSpec(
    name="convert",
    argv=_argv,
    log_path=_log_path,
    outputs=_outputs,
    job_id_env="PAGESPEAK_JOB_ID",
)


def run_job(job_row: dict[str, Any]) -> None:
    """Run one claimed conversion job to completion (blocking)."""
    run_subprocess_job(job_row, SPEC)


def start_workers(cfg: WebConfig) -> WorkerHandle:
    """Register the kind and start ``cfg.concurrency`` claim-loop workers."""
    register_conversion_kind()
    return _pf_start_workers(
        kinds=[CONVERSION_KIND],
        run=run_job,
        concurrency=cfg.concurrency,
        worker_id_prefix="web",
    )
