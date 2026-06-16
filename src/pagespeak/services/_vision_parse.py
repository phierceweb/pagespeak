"""Vision response parsing: model output → `Diagram`.

The narrow concern of turning a vision backend's raw text response into a
`Diagram` (tolerant JSON parse + field normalization). Imported by the
backends' `analyze()` and re-exported from `_diagrams` for the test surface.
Self-contained — depends only on pf-core + models, so there is no import cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pf_core.llm.parse import parse_llm_json
from pf_core.log import get_logger

from ..models._models import Diagram

logger = get_logger(__name__)


def _build_diagram(image_path: Path, raw_text: str) -> Diagram:
    parsed = _parse_response(raw_text, image_path)
    return Diagram(
        image_path=image_path,
        caption=parsed["caption"],
        mermaid=parsed["mermaid"],
        diagram_type=parsed.get("diagram_type"),
    )


def _normalize_parsed(data: dict[str, Any], image_path: Path) -> dict[str, Any]:
    return {
        "is_diagram": bool(data.get("is_diagram", False)),
        "diagram_type": data.get("diagram_type"),
        "caption": str(data.get("caption", "") or f"Image at {image_path.name}."),
        "mermaid": data.get("mermaid") if data.get("is_diagram") else None,
    }


def _parse_response(text: str, image_path: Path) -> dict[str, Any]:
    """Parse JSON from the model. Tolerates markdown fences and surrounding
    free-form text (Claude Code may include "I'll analyze this image..."
    preamble or tool-use traces).

    Delegates to `pf_core.llm.parse.parse_llm_json` which walks the full
    fallback pipeline: strip fences → json.loads → balanced-brace extract
    → truncation recovery → json_repair (permissive last-resort).
    """
    parsed = parse_llm_json(text, expect="object")
    if isinstance(parsed, dict):
        return _normalize_parsed(parsed, image_path)

    logger.warning("could_not_parse_diagram_response path=%s text=%r", image_path, text[:200])
    return {
        "is_diagram": False,
        "diagram_type": None,
        "caption": f"Image at {image_path.name} (description unavailable).",
        "mermaid": None,
    }
