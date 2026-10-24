"""How a chunked ingest is sized: pages per chunk and the worker count, each
from an explicit value, then `PAGESPEAK_CHUNK_PAGES` / `PAGESPEAK_WORKERS`, then
the default; and whether the CLI chunks at all."""

from __future__ import annotations

from pathlib import Path

from pw_foundation.log import get_logger
from pw_foundation.utils.env import resolve_positive_int

logger = get_logger(__name__)

DEFAULT_CHUNK_PAGES = 50
CHUNK_PAGES_ENV_VAR = "PAGESPEAK_CHUNK_PAGES"
WORKERS_ENV_VAR = "PAGESPEAK_WORKERS"
DEFAULT_WORKERS = 4


def resolve_chunk_pages(explicit: int | None = None) -> int:
    """Pick chunk size (pages): explicit param > env var > default 50.

    Operational tunable (env-configurable) — larger chunks
    mean fewer Marker model-loads (~30s each), smaller chunks mean
    finer-grained resume. Memory-bound: each worker holds its chunk in
    RAM. Delegates to `pw_foundation.utils.env.resolve_positive_int`: an
    explicit `< 1` raises `ValueError`; a malformed or out-of-range env
    value warns and falls back to the default.
    """
    return resolve_positive_int(
        explicit, CHUNK_PAGES_ENV_VAR, default=DEFAULT_CHUNK_PAGES, min_value=1
    )


def resolve_workers(explicit: int | None = None) -> int:
    """Pick worker count: explicit param > env var > default 4.

    Delegates to `pw_foundation.utils.env.resolve_positive_int`. An explicit
    `< 1` raises `ValueError` (caller bug — fail fast). A malformed env
    var emits a structured `env_var_malformed` warning and falls back to
    the default; an out-of-range env value (e.g. `"-3"` that parses but
    isn't positive) emits `env_var_out_of_range` and falls back rather
    than allowed to deadlock the ProcessPoolExecutor.
    """
    return resolve_positive_int(explicit, WORKERS_ENV_VAR, default=DEFAULT_WORKERS, min_value=1)


def resolve_cli_workers(
    explicit: int | None,
    source: Path | None = None,
    *,
    chunk_unsafe: bool = False,
) -> int:
    """Pick the CLI `--workers` value: explicit flag > `PAGESPEAK_WORKERS` > 1.

    Separate from `resolve_workers`, which sizes the pool once chunking is
    already chosen and so defaults to `DEFAULT_WORKERS`. This decides *whether*
    to chunk, where the default must stay 1.

    An env-derived value is clamped to 1 for a source the chunked path cannot
    take (anything but a PDF file) and for a run it cannot serve (`chunk_unsafe`):
    an ambient setting must never change what a command does. An explicit
    `--workers` is never clamped — the chunked path's own errors answer that.
    """
    if explicit is not None and explicit < 1:
        # `resolve_positive_int` would name the env var, which the user never set.
        raise ValueError(f"--workers must be >= 1 (got {explicit})")
    n = resolve_positive_int(explicit, WORKERS_ENV_VAR, default=1, min_value=1)
    if explicit is not None or n == 1:
        return n
    chunkable = source is not None and source.is_file() and source.suffix.lower() == ".pdf"
    if chunkable and not chunk_unsafe:
        return n
    logger.info(
        "cli_workers_env_clamped requested=%d chunkable=%s chunk_unsafe=%s",
        n,
        chunkable,
        chunk_unsafe,
    )
    return 1
