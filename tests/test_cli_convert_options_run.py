"""Tests for cli._convert_options_run."""

from __future__ import annotations

from typer.models import ArgumentInfo, OptionInfo

from pagespeak.cli import _convert_options_run as opts

OPTIONS = {
    "DIAGRAMS": ("diagrams", ("--diagrams/--no-diagrams",), True),
    "VISION_BACKEND": ("vision_backend", ("--vision-backend",), None),
    "VISION_MODEL": ("vision_model", ("--vision-model",), None),
    "VISION_CONCURRENCY": ("vision_concurrency", ("--vision-concurrency",), None),
    "VISION_CACHE_ONLY": ("vision_cache_only", ("--vision-cache-only",), False),
    "VISION_ALL_IMAGES": ("vision_all_images", ("--vision-all-images",), False),
    "PRESERVE_ALT": ("preserve_alt", ("--preserve-alt",), False),
    "SPLIT_SECTIONS": ("split_sections", ("--split-sections/--no-split-sections",), False),
    "NESTED_SPLIT": ("nested_split", ("--nested-split/--no-nested-split",), False),
    "SPLIT_MIN_LEVEL": ("split_min_level", ("--split-min-level",), None),
    "SPLIT_MAX_LEVEL": ("split_max_level", ("--split-max-level",), None),
    "SPLIT_TARGET_KB": ("split_target_kb", ("--split-target-kb",), None),
    "MIN_BODY_CHARS": ("min_body_chars", ("--min-body-chars",), None),
    "ENGLISH_ONLY": ("english_only", ("--english-only/--no-english-only",), False),
    "NORMALIZE_HEADINGS": (
        "normalize_headings",
        ("--normalize-headings/--no-normalize-headings",),
        False,
    ),
    "NORMALIZE_HEADINGS_MODE": (
        "normalize_headings_mode",
        ("--normalize-headings-mode",),
        "heuristic",
    ),
    "NORMALIZE_HEADINGS_MODEL": ("normalize_headings_model", ("--normalize-headings-model",), None),
    "NORMALIZE_HEADINGS_BACKEND": (
        "normalize_headings_backend",
        ("--normalize-headings-backend",),
        None,
    ),
    "PROVENANCE": ("provenance", ("--provenance/--no-provenance",), False),
    "SOURCE_TYPE": ("source_type", ("--source-type",), None),
    "SOURCE_LABEL": ("source_label", ("--source-label",), None),
    "INHERIT": ("inherit", ("--inherit/--no-inherit",), True),
    "RERUN_FROM": ("rerun_from", ("--rerun-from",), None),
    "START": ("start", ("--from",), None),
    "STOP_AFTER": ("stop_after", ("--stop-after",), None),
    "WORKERS": ("workers", ("--workers", "-w"), None),
    "ALLOW_PARTIAL_INGEST": ("allow_partial_ingest", ("--allow-partial-ingest",), False),
}


def _declared() -> dict[str, OptionInfo | ArgumentInfo]:
    return {n: v for n, v in vars(opts).items() if isinstance(v, OptionInfo | ArgumentInfo)}


def test_each_option_is_the_default_of_exactly_one_convert_parameter(
    convert_parameters: dict[str, object],
) -> None:
    options = _declared()
    assert options
    for name, value in options.items():
        assert sum(d is value for d in convert_parameters.values()) == 1, name


def test_options_feed_their_parameter_with_their_flags_and_defaults(
    convert_parameters: dict[str, object],
) -> None:
    fed = {id(default): param for param, default in convert_parameters.items()}
    declared = {n: (fed.get(id(v)), v.param_decls, v.default) for n, v in _declared().items()}
    assert declared == OPTIONS
