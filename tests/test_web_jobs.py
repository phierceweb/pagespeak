from __future__ import annotations

import pytest

from pagespeak.web._jobs import (
    CONVERSION_KIND,
    ConversionInputs,
    ConversionOptions,
    register_conversion_kind,
)


def test_register_is_idempotent():
    from pf_core.jobs import clear_registry, get_kind

    clear_registry()
    register_conversion_kind()
    register_conversion_kind()  # no raise
    assert get_kind(CONVERSION_KIND).kind == CONVERSION_KIND


def test_inputs_schema_defaults():
    inp = ConversionInputs(out_dir="/x/out/doc")
    assert inp.start is None
    assert inp.stop_after is None
    assert inp.confirmed_vision is False
    assert isinstance(inp.options, ConversionOptions)
    assert inp.options.diagrams is True
    assert inp.options.vision_backend is None


def test_inputs_reject_bad_phase():
    with pytest.raises(ValueError):
        ConversionInputs(out_dir="/x", start="banana")
