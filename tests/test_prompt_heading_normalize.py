"""Tests for `pagespeak.prompts._heading_normalize` — the YAML-loaded
heading-normalize prompt.

Mirrors the shape of `tests/test_prompt_diagram.py` and the
`test_prompt_heading_normalize_full` cases in `test_heading_normalize.py`.
"""

from __future__ import annotations


def test_heading_normalize_prompt_yaml_loads_at_import_time() -> None:
    """Loading the prompt module renders the YAML and exports the
    required constants. Catches schema breakage early."""
    from pagespeak.prompts._heading_normalize import (
        HEADING_NORMALIZE_PROMPT,
        HEADING_NORMALIZE_PROMPT_VERSION,
    )

    assert isinstance(HEADING_NORMALIZE_PROMPT, str)
    assert HEADING_NORMALIZE_PROMPT_VERSION >= 1
    # Sanity: prompt text mentions heading levels and the expected
    # output shape.
    assert "heading" in HEADING_NORMALIZE_PROMPT.lower()
    assert "<index>" in HEADING_NORMALIZE_PROMPT or "1: 4" in HEADING_NORMALIZE_PROMPT


def test_build_normalize_prompt_renders_headings_block() -> None:
    """The user-message renderer substitutes the headings block via
    the `@@HEADINGS@@` token (`style="@@"` since the YAML body may
    contain literal `{` / `}` in examples)."""
    from pagespeak.prompts._heading_normalize import build_normalize_prompt

    rendered = build_normalize_prompt("1: 4 Chapter 1 Introduction\n2: 4 1.1 Foo\n3: 4 1.2 Bar")
    assert "1: 4 Chapter 1 Introduction" in rendered
    assert "2: 4 1.1 Foo" in rendered
    assert "3: 4 1.2 Bar" in rendered
    # The system prompt is concatenated with the user template; both
    # parts should appear.
    assert "heading" in rendered.lower()


def test_service_module_imports_constants_from_yaml_loader() -> None:
    """`services._heading_normalize` exports `NORMALIZE_PROMPT_VERSION`
    sourced from the new YAML loader (backward-compat constant name)."""
    from pagespeak.prompts._heading_normalize import HEADING_NORMALIZE_PROMPT_VERSION
    from pagespeak.services._heading_normalize import NORMALIZE_PROMPT_VERSION

    assert NORMALIZE_PROMPT_VERSION == HEADING_NORMALIZE_PROMPT_VERSION
