from __future__ import annotations

import pytest

from pagespeak.backends._docx_dispatch import (
    DEFAULT_DOCX_BACKEND,
    get_docx_converter,
)


def test_default_backend_is_markitdown() -> None:
    assert DEFAULT_DOCX_BACKEND == "markitdown"


def test_get_markitdown_returns_callable() -> None:
    from pagespeak.backends._docx import convert_with_markitdown

    assert get_docx_converter("markitdown") is convert_with_markitdown


def test_get_python_docx_returns_structured() -> None:
    pytest.importorskip("docx")  # structure-faithful backend needs python-docx
    from pagespeak.backends._docx_structured import convert_structured

    assert get_docx_converter("python-docx") is convert_structured


def test_unknown_backend_value_errors() -> None:
    with pytest.raises(ValueError, match="Unknown docx_backend"):
        get_docx_converter("bogus")  # type: ignore[arg-type]
