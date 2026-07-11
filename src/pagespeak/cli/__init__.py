"""Typer CLI for pagespeak.

Subcommands:

  pagespeak convert <input> [...]    one-shot or multi-worker conversion
  pagespeak ingest <input> [...]     backend phase only (produce raw.md)
  pagespeak baseline <output> [...]  snapshot / diff runs
  pagespeak invalidate <output> [...] bust caches at a stage
  pagespeak deliver <output> [...]   strip an output dir to delivery-ready files
  pagespeak audit <paths> [...]      scan converted output for conversion defects
  pagespeak vision-audit <paths> [.] flag likely-confabulated vision captions
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
from ._vision_audit import register as _register_vision_audit

# Logging is bootstrapped at package import (see pagespeak/__init__.py).


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
_register_vision_audit(app)
_register_repair(app)


def main() -> None:
    # Init the llm_runs tracking DB (SQLite default; DATABASE_URL overrides).
    # Non-fatal on failure; library consumers opt in via pagespeak._db.init_db().
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
