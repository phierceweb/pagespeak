"""1:1 mirror of `orchestrators/_phase.py` — the `Phase` protocol.

Verifies every concrete phase structurally satisfies `Phase` (it is
`runtime_checkable`) and that `build_phases()` returns them in the
canonical pipeline order.
"""

from __future__ import annotations

from pagespeak.orchestrators._phase import Phase
from pagespeak.orchestrators._phases import build_phases

_EXPECTED_ORDER = ["ingest", "cleanup", "normalize", "repair", "structure", "vision", "split"]


def test_every_built_phase_satisfies_protocol() -> None:
    phases = build_phases()
    for p in phases:
        assert isinstance(p, Phase)  # runtime_checkable structural check
        assert isinstance(p.name, str) and p.name
        assert callable(p.is_fresh)
        assert callable(p.run)


def test_build_phases_canonical_order() -> None:
    assert [p.name for p in build_phases()] == _EXPECTED_ORDER


def test_a_non_phase_object_is_not_a_phase() -> None:
    assert not isinstance(object(), Phase)
