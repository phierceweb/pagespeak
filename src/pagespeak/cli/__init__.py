"""Typer CLI for pagespeak.

Subcommands:

  pagespeak convert <input> [...]    one-shot or multi-worker conversion
  pagespeak ingest <input> [...]     backend phase only (produce raw.md)
  pagespeak baseline <output> [...]  snapshot / diff runs
  pagespeak invalidate <output> [...] bust caches at a stage
  pagespeak deliver <output> [...]   strip an output dir to delivery-ready files
  pagespeak audit <paths> [...]      scan converted output for conversion defects
  pagespeak repair-tables <out> [...] splice Docling grids into collapsed tables
"""

from __future__ import annotations

import sys

import typer

from ._audit import register as _register_audit
from ._baseline import register as _register_baseline
from ._convert import register as _register_convert
from ._deliver import register as _register_deliver
from ._ingest import register as _register_ingest
from ._invalidate import register as _register_invalidate
from ._repair import register as _register_repair

# Logging is bootstrapped at `pagespeak/__init__.py` (the package root) so that
# both CLI and library users hit the same configuration before any module-level
# `get_logger(__name__)` call lazy-triggers pf-core's `setup_logging` with the
# wrong `app_logger_name`. See the comment in `pagespeak/__init__.py` for the
# full rationale.


app = typer.Typer(
    name="pagespeak",
    help="Convert PDFs and Office docs to LLM-friendly markdown.",
    add_completion=False,
    no_args_is_help=True,
)

_VALID_CLEANUP_LEVELS: tuple[str, ...] = ("off", "basic", "aggressive")
_VALID_CROSS_REFS: tuple[str, ...] = ("keep", "strip", "remap")
_VALID_VISION_BACKENDS: tuple[str, ...] = ("anthropic", "claude_code", "openrouter")
_VALID_PDF_BACKENDS: tuple[str, ...] = ("marker", "docling", "tophat")
_VALID_NORMALIZE_MODES: tuple[str, ...] = ("heuristic", "llm", "llm_full", "auto")
_VALID_PRESETS: tuple[str, ...] = ("rag-default", "flat", "textbook", "archival", "qti")
_VALID_NORMALIZE_HEADINGS_BACKENDS: tuple[str, ...] = (
    "claude_code",
    "anthropic",
    "openrouter",
)


def _validate_cleanup(value: str) -> str:
    if value not in _VALID_CLEANUP_LEVELS:
        raise typer.BadParameter(f"--cleanup must be one of {_VALID_CLEANUP_LEVELS}; got {value!r}")
    return value


def _validate_cross_refs(value: str) -> str:
    if value not in _VALID_CROSS_REFS:
        raise typer.BadParameter(f"--cross-refs must be one of {_VALID_CROSS_REFS}; got {value!r}")
    return value


def _validate_vision_backend(value: str) -> str:
    if value not in _VALID_VISION_BACKENDS:
        raise typer.BadParameter(
            f"--vision-backend must be one of {_VALID_VISION_BACKENDS}; got {value!r}"
        )
    return value


def _validate_pdf_backend(value: str) -> str:
    if value not in _VALID_PDF_BACKENDS:
        raise typer.BadParameter(
            f"--pdf-backend must be one of {_VALID_PDF_BACKENDS}; got {value!r}"
        )
    return value


def _validate_normalize_mode(value: str) -> str:
    if value not in _VALID_NORMALIZE_MODES:
        raise typer.BadParameter(
            f"--normalize-headings-mode must be one of {_VALID_NORMALIZE_MODES}; got {value!r}"
        )
    return value


def _validate_preset(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in _VALID_PRESETS:
        raise typer.BadParameter(f"--preset must be one of {_VALID_PRESETS}; got {value!r}")
    return value


def _validate_normalize_headings_backend(value: str | None) -> str | None:
    """Per-task backend selection for heading-normalize.

    None (default) means "don't touch env vars — leave whatever the
    user set in .env or shell". When provided, the convert subcommand
    sets both `PAGESPEAK_HEADING_NORMALIZE_BACKEND` and
    `PAGESPEAK_HEADING_NORMALIZE_FULL_BACKEND` env vars so both modes
    use the same backend for the run.
    """
    if value is None:
        return None
    if value not in _VALID_NORMALIZE_HEADINGS_BACKENDS:
        raise typer.BadParameter(
            f"--normalize-headings-backend must be one of "
            f"{_VALID_NORMALIZE_HEADINGS_BACKENDS}; got {value!r}"
        )
    return value


_register_convert(
    app,
    validate_cleanup=_validate_cleanup,
    validate_cross_refs=_validate_cross_refs,
    validate_vision_backend=_validate_vision_backend,
    validate_pdf_backend=_validate_pdf_backend,
    validate_normalize_mode=_validate_normalize_mode,
    validate_preset=_validate_preset,
    validate_normalize_headings_backend=_validate_normalize_headings_backend,
)

_register_ingest(app, validate_pdf_backend=_validate_pdf_backend)
_register_invalidate(app)
_register_baseline(app)
_register_deliver(app)
_register_audit(app)
_register_repair(app)


def main() -> None:
    # Logging is bootstrapped at `pagespeak/__init__.py` (package import time).
    #
    # initialize the LLM-call tracking DB at CLI startup so
    # every `invoke_agent` call during the run gets persisted to
    # `llm_runs` (default: SQLite at `~/.pagespeak/llm_tracking.db`;
    # override via `DATABASE_URL`). Failure is non-fatal — a bad
    # `DATABASE_URL` should not block conversions. Library consumers
    # opt-in by calling `pagespeak._db.init_db()` themselves; without
    # it `_agent_runtime` skips the write.
    from .._db import init_db

    try:
        init_db()
    except Exception as exc:
        from pf_core.log import get_logger

        get_logger(__name__).warning(
            "pagespeak_db_init_failed error=%r — LLM call tracking disabled this run", exc
        )

    try:
        app()
    except KeyboardInterrupt:
        typer.echo("interrupted", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
