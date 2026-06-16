"""Build the ``pagespeak convert`` argv + per-job paths for the worker.

Separated from ``_worker`` (which runs the process and manages job state) so
that command construction is its own small, independently testable concern.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pagespeak.web._jobs import ConversionInputs


def resolve_pagespeak_bin() -> str:
    """Path to the venv's pagespeak entrypoint (same venv as this process)."""
    candidate = Path(sys.executable).parent / "pagespeak"
    return str(candidate) if candidate.exists() else "pagespeak"


def log_path(out_dir: Path, job_id: int) -> Path:
    """Per-job subprocess log file, under ``<out_dir>/.web-logs/``."""
    return out_dir / ".web-logs" / f"job-{job_id}.log"


def build_command(inp: ConversionInputs, *, pagespeak_bin: str) -> list[str]:
    """Build the ``pagespeak convert`` argv for a job's phase slice.

    - start is None or "ingest" -> input is the SOURCE file, ``-o out_dir``.
    - start is a later phase -> input is the OUT dir (dir-mode), ``--from``.
    """
    opts = inp.options
    starts_at_ingest = inp.start in (None, "ingest")

    cmd: list[str] = [pagespeak_bin, "convert"]
    if starts_at_ingest:
        if not inp.source_path:
            raise ValueError("a full/ingest run needs source_path")
        cmd += [inp.source_path, "-o", inp.out_dir]
    else:
        cmd += [inp.out_dir]

    if inp.start == "ingest":
        cmd += ["--from", "ingest"]
    elif inp.start is not None:
        cmd += ["--from", inp.start]
    if inp.stop_after is not None:
        cmd += ["--stop-after", inp.stop_after]
    if opts.rerun_from:
        cmd += ["--rerun-from", opts.rerun_from]

    if opts.preset:
        cmd += ["--preset", opts.preset]
    if not opts.diagrams:
        cmd += ["--no-diagrams"]
    if opts.vision_backend:
        cmd += ["--vision-backend", opts.vision_backend]
    if opts.vision_cache_only:
        cmd += ["--vision-cache-only"]
    if opts.cleanup:
        cmd += ["--cleanup", opts.cleanup]
    if opts.split_sections:
        cmd += ["--split-sections"]
    if opts.nested_split:
        cmd += ["--nested-split"]
    if opts.normalize_headings:
        cmd += ["--normalize-headings"]
        if opts.normalize_headings_mode:
            cmd += ["--normalize-headings-mode", opts.normalize_headings_mode]
        if opts.normalize_headings_backend:
            cmd += ["--normalize-headings-backend", opts.normalize_headings_backend]
    if opts.pdf_backend:
        cmd += ["--pdf-backend", opts.pdf_backend]
    if opts.docx_backend:
        cmd += ["--docx-backend", opts.docx_backend]
    if opts.workers and opts.workers != 1:
        cmd += ["--workers", str(opts.workers)]
    if opts.source_type:
        cmd += ["--source-type", opts.source_type]
    if opts.source_label:
        cmd += ["--source-label", opts.source_label]
    return cmd
