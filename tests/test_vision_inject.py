"""Tests for services._vision_inject."""

from __future__ import annotations

from pathlib import Path


def test_inject_matches_an_encoded_ref_and_a_name_holding_a_hash() -> None:
    from pagespeak.models._models import Diagram
    from pagespeak.services._vision_inject import inject_diagrams

    def diagram(name: str) -> Diagram:
        return Diagram(
            image_path=Path(name), caption=f"cap {name}", mermaid=None, diagram_type=None
        )

    md = "![x](images/my%20shot.png)\n\n![y](images/C#.png)"
    out = inject_diagrams(md, {"my shot.png": diagram("my shot.png"), "C#.png": diagram("C#.png")})
    assert "![cap my shot.png](images/my%20shot.png)" in out
    assert "![cap C#.png](images/C#.png)" in out
