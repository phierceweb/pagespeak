"""`to_markdown`'s last step: the master `<stem>.md` and `.pagespeak-run.json`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pw_foundation.log import get_logger
from pw_foundation.utils.io import atomic_write_text

from ..models._models import IngestResult
from ._context import PipelineContext
from ._dispatch_setup import _now_utc_iso, resolved_flags_from_ctx

logger = get_logger(__name__)


def write_final_outputs(
    ctx: PipelineContext,
    result: IngestResult,
    *,
    src: Path,
    out: Path,
    effective_stem: str,
    dir_mode: bool,
    qti_mode: bool,
    preset: str | None,
    stop_after: str | None,
    started_at: str,
    llm_call_records: list[dict[str, Any]],
) -> None:
    """Write the master document and stamp the resolved config into the run
    record, so re-run drift is a one-line diff. A failed record write is
    logged, not raised."""
    from .. import __version__
    from ..services._provenance import persistable_source_identity
    from ..services._run_record import summarize_llm_calls, write_run_record

    # Written by the library so every consumer gets it. An earlier stop leaves
    # result.markdown as an intermediate checkpoint — writing that would
    # clobber the real final document.
    if stop_after in (None, "vision", "split"):
        atomic_write_text(out / f"{effective_stem}.md", result.markdown)

    finished_at = _now_utc_iso()
    resolved_flags = resolved_flags_from_ctx(ctx)
    # The run record SHA-256s the input as a file. A QTI export can be a
    # directory — record its manifest (a stable per-export fingerprint).
    record_input = src
    if qti_mode and src.is_dir():
        record_input = src / "imsmanifest.xml"
    # Resolve BEFORE writing: dir-mode reads the prior record to carry the
    # original source identity forward (this run's `input` is a checkpoint).
    source_identity = None if qti_mode else persistable_source_identity(src, out, dir_mode=dir_mode)
    try:
        write_run_record(
            out,
            version=__version__,
            preset=preset,
            resolved_flags=resolved_flags,
            input_path=record_input,
            started_at=started_at,
            finished_at=finished_at,
            section_count=ctx.section_count,
            image_count=len(result.images),
            llm_calls=summarize_llm_calls(llm_call_records),
            source_identity=source_identity,
        )
    except OSError as e:
        logger.warning("run_record_write_failed path=%s error=%s", out, e)
