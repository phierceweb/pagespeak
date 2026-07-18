"""Run-record flag inheritance for `pagespeak convert`.

When convert targets an existing output dir holding a
`.pagespeak-run.json`, flags the user didn't pass explicitly default to
the record's `resolved_flags` — so a bare `--rerun-from` rebuilds
`sections/` with the original shape instead of silently dropping it.
Explicit CLI flags win; an explicit `--preset` wins over the record for
the preset-controlled flags; `--no-inherit` disables the mechanism.

LLM/engine/runtime selection (`diagrams`, `vision_*`, `preserve_alt`,
`normalize_headings_model`, `device`) is never inherited: engine choice
and spend stay per-invocation decisions, and a device is machine-bound.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import typer
from pf_core.log import get_logger

from ..services._run_record import RUN_RECORD_FILENAME, read_run_record

logger = get_logger(__name__)

# typer params a preset can supply. The CLI passes None to `to_markdown`
# for any of these the user didn't set, so the library-side
# preset+default resolver picks the value.
_PRESET_CONTROLLED_FLAGS: tuple[str, ...] = (
    "cleanup",
    "split_sections",
    "nested_split",
    "split_min_level",
    "normalize_headings",
    "normalize_headings_mode",
    "strip_frontmatter",
    "provenance",
)

# Record keys a re-run may inherit, with the JSON type each must carry.
# Deliberately deterministic/$0/output-shaping only (see module docstring
# for what never inherits).
_FLAG_TYPES: dict[str, type] = {
    "cleanup": str,
    "cross_refs": str,
    "split_sections": bool,
    "nested_split": bool,
    "split_min_level": int,
    "split_max_level": int,
    "split_target_kb": int,
    "english_only": bool,
    "min_body_chars": int,
    "regenerate_toc": bool,
    "decoration_threshold": int,
    "decoration_hamming_distance": int,
    "pdf_backend": str,
    "repair_tables": bool,
    "docx_backend": str,
    "docx_outline_heading_depth": int,
    "force_ocr": bool,
    "page_range": str,
    "html_base_url": str,
    "normalize_headings": bool,
    "normalize_headings_mode": str,
    "strip_frontmatter": bool,
    "provenance": bool,
    "source_type": str,
    "source_label": str,
}

INHERITABLE_FLAGS: tuple[str, ...] = tuple(_FLAG_TYPES)


def _is_commandline_source(source: object) -> bool:
    """True if a Click/Typer parameter source is COMMANDLINE.

    Compared by enum *name*, not identity: typer >= 0.26 vendors its own
    Click, so `ctx.get_parameter_source()` returns a member that is never
    equal to `click.core.ParameterSource.COMMANDLINE`. A name comparison
    is robust across the stdlib-click and vendored-click enums."""
    return getattr(source, "name", None) == "COMMANDLINE"


def explicit_command_line_params(ctx: typer.Context, names: Iterable[str]) -> set[str]:
    """The subset of `names` that came from the COMMAND LINE (not a typer
    default), via Click's `get_parameter_source` — a default-equal explicit
    pass still counts as user-set. Empty set on any unexpected Click API
    error so an API change doesn't crash the convert command."""
    explicit: set[str] = set()
    try:
        for name in names:
            if _is_commandline_source(ctx.get_parameter_source(name)):
                explicit.add(name)
    except (AttributeError, TypeError):
        pass
    return explicit


def _type_ok(value: Any, expected: type) -> bool:
    if expected is bool:
        return isinstance(value, bool)
    if expected is int:  # bool is an int subclass; a JSON true is not a level
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def inherited_updates(
    record: Mapping[str, Any],
    *,
    explicit: set[str],
    preset_explicit: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Compute the flag defaults a run record supplies: `(updates, warnings)`.

    A flag inherits when it is inheritable, present and non-None in the
    record's `resolved_flags`, not explicitly passed on the command line,
    and not preset-controlled while an explicit `--preset` is in play.
    Wrong-typed record values are skipped, one warning line each."""
    flags = record.get("resolved_flags")
    if not isinstance(flags, dict):
        return {}, []
    updates: dict[str, Any] = {}
    warnings: list[str] = []
    for name in INHERITABLE_FLAGS:
        if name in explicit or (preset_explicit and name in _PRESET_CONTROLLED_FLAGS):
            continue
        value = flags.get(name)
        if value is None:
            continue
        expected = _FLAG_TYPES[name]
        if not _type_ok(value, expected):
            warnings.append(f"{name}={value!r} (expected {expected.__name__}) — not inherited")
            continue
        updates[name] = value
    return updates, warnings


def apply_run_record_defaults(
    *,
    output_dir: Path,
    explicit: set[str],
    validators: Mapping[str, Callable[[str], str]],
    echo: Callable[[str], None],
) -> dict[str, Any]:
    """Load `<output_dir>/.pagespeak-run.json` and return the inherited
    flag defaults, echoing one notice line naming them.

    A missing or unreadable record inherits nothing. Inherited values
    named in `validators` are validated; a rejected value raises
    `typer.BadParameter` pointing at the record."""
    record = read_run_record(output_dir)
    if record is None:
        return {}
    updates, warnings = inherited_updates(
        record, explicit=explicit, preset_explicit="preset" in explicit
    )
    record_path = output_dir / RUN_RECORD_FILENAME
    for line in warnings:
        logger.warning("run_record_flag_skipped %s path=%s", line, record_path)
    for name, validate in validators.items():
        if name in updates:
            try:
                updates[name] = validate(updates[name])
            except typer.BadParameter as exc:
                raise typer.BadParameter(
                    f"{RUN_RECORD_FILENAME} resolved_flags.{name}={updates[name]!r} is "
                    f"invalid ({exc.message}). Fix the record, pass the flag explicitly, "
                    f"or use --no-inherit."
                ) from exc
    if updates:
        rendered = ", ".join(f"{k}={updates[k]!r}" for k in INHERITABLE_FLAGS if k in updates)
        echo(
            f"defaults inherited from {RUN_RECORD_FILENAME}: {rendered} "
            f"(explicit flags win; --no-inherit for bare defaults)"
        )
    return updates
