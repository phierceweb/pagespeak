"""In-process conversion worker.

One job = one ``pagespeak convert`` subprocess covering the job's phase
slice, run with ``PAGESPEAK_JOB_ID`` set so LLM rows attribute to the job.
Progress is read from on-disk checkpoints by the scanner; this module only
runs the process, captures its log, and transitions the job.
"""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pf_core.log import get_logger

from pagespeak.web._command import build_command, log_path, resolve_pagespeak_bin
from pagespeak.web._config import WebConfig
from pagespeak.web._jobs import (
    CONVERSION_KIND,
    ConversionInputs,
    ConversionOutputs,
    register_conversion_kind,
)

logger = get_logger(__name__)

# job_id -> running Popen, so the cancel endpoint can terminate it.
_RUNNING: dict[int, subprocess.Popen[bytes]] = {}
_RUNNING_LOCK = threading.Lock()


def run_job(job_row: dict[str, Any]) -> None:
    """Run one claimed conversion job to completion (blocking)."""
    from pf_core.jobs import Job, JobRepo

    job_id = int(job_row["id"])
    inp = ConversionInputs.model_validate(job_row["inputs"] or {})
    out_dir = Path(inp.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lp = log_path(out_dir, job_id)
    lp.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_command(inp, pagespeak_bin=resolve_pagespeak_bin())
    env = dict(os.environ)
    env["PAGESPEAK_JOB_ID"] = str(job_id)

    repo = JobRepo()
    with Job(job_id, repo=repo) as job:
        job.transition("running")
        job.event("started", " ".join(cmd))
        with lp.open("w", encoding="utf-8") as log:
            log.write(f"$ {' '.join(cmd)}\n\n")
            log.flush()
            proc: subprocess.Popen[bytes] = subprocess.Popen(
                cmd, stdout=log, stderr=subprocess.STDOUT, env=env
            )
            with _RUNNING_LOCK:
                _RUNNING[job_id] = proc
            try:
                rc = proc.wait()
            finally:
                with _RUNNING_LOCK:
                    _RUNNING.pop(job_id, None)

        outputs = ConversionOutputs(
            phases=f"{inp.start or 'ingest'}..{inp.stop_after or 'split'}",
            returncode=rc,
        )
        if (repo.get(job_id) or {}).get("status") == "canceled":
            return
        if rc == 0:
            job.outputs = outputs
            job.transition("succeeded")
        else:
            job.transition("failed", error=f"convert exited {rc} (see {lp})")


def terminate_job(job_id: int) -> bool:
    """Terminate a running job's subprocess if present. Returns True if killed."""
    with _RUNNING_LOCK:
        proc = _RUNNING.get(job_id)
    if proc is None:
        return False
    proc.terminate()
    return True


@dataclass
class WorkerHandle:
    threads: list[threading.Thread]
    stop_event: threading.Event


def _loop(worker_id: str, stop_event: threading.Event, poll: float = 1.0) -> None:
    from pf_core.jobs import JobRepo

    repo = JobRepo()
    while not stop_event.is_set():
        try:
            job = repo.claim_next(kinds=[CONVERSION_KIND], worker_id=worker_id)
        except Exception as exc:
            logger.warning("worker_claim_failed error=%r", exc)
            stop_event.wait(poll)
            continue
        if job is None:
            stop_event.wait(poll)
            continue
        try:
            run_job(job)
        except Exception as exc:
            logger.warning("worker_run_failed job=%s error=%r", job.get("id"), exc)


def start_workers(cfg: WebConfig) -> WorkerHandle:
    """Register the kind and start ``cfg.concurrency`` daemon worker threads."""
    register_conversion_kind()
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    for i in range(max(1, cfg.concurrency)):
        t = threading.Thread(target=_loop, args=(f"web-{os.getpid()}-{i}", stop_event), daemon=True)
        t.start()
        threads.append(t)
    logger.debug("pagespeak_web_worker_started count=%d", len(threads))
    return WorkerHandle(threads=threads, stop_event=stop_event)


def stop_workers(handle: WorkerHandle) -> None:
    handle.stop_event.set()
    for t in handle.threads:
        t.join(timeout=2.0)
