"""Tests for cli._convert_options_source."""

from __future__ import annotations

from pathlib import Path

from typer.models import ArgumentInfo, OptionInfo

from pagespeak.cli import _convert_options_source as opts

OPTIONS = {
    "INPUT_PATH": ("input_path", None, ...),
    "OUTPUT_DIR": ("output_dir", ("--output-dir", "-o"), Path("./out")),
    "PRESET": ("preset", ("--preset",), None),
    "FORCE_OCR": ("force_ocr", ("--force-ocr/--no-force-ocr",), False),
    "DEVICE": ("device", ("--device",), None),
    "PAGE_RANGE": ("page_range", ("--page-range",), None),
    "HTML_BASE_URL": ("html_base_url", ("--html-base-url",), None),
    "CLEANUP": ("cleanup", ("--cleanup",), "basic"),
    "CROSS_REFS": ("cross_refs", ("--cross-refs",), "keep"),
    "PDF_BACKEND": ("pdf_backend", ("--pdf-backend",), "marker"),
    "HEADING_HIERARCHY": (
        "heading_hierarchy",
        ("--heading-hierarchy/--no-heading-hierarchy",),
        False,
    ),
    "PDF_BACKEND_KWARGS": ("pdf_backend_kwargs", ("--pdf-backend-kwargs",), None),
    "DECORATION_THRESHOLD": ("decoration_threshold", ("--decoration-threshold",), None),
    "DECORATION_HAMMING_DISTANCE": (
        "decoration_hamming_distance",
        ("--decoration-hamming-distance",),
        None,
    ),
    "REPAIR_TABLES": ("repair_tables", ("--repair-tables/--no-repair-tables",), False),
    "DOCX_BACKEND": ("docx_backend", ("--docx-backend",), "markitdown"),
    "DOCX_OUTLINE_HEADING_DEPTH": (
        "docx_outline_heading_depth",
        ("--docx-outline-heading-depth",),
        0,
    ),
    "STRIP_FRONTMATTER": (
        "strip_frontmatter",
        ("--strip-frontmatter/--no-strip-frontmatter",),
        False,
    ),
    "ANSWER_KEY": ("answer_key", ("--answer-key/--no-answer-key",), True),
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


def test_convert_refuses_an_input_that_does_not_exist(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from pagespeak.cli import app

    info = opts.INPUT_PATH
    assert (info.exists, info.readable, info.dir_okay) == (True, True, True)
    result = CliRunner().invoke(app, ["convert", str(tmp_path / "missing.pdf"), "--no-diagrams"])
    assert result.exit_code == 2
