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


class VisionParseError(Exception):
    """The model's reply could not be parsed into a caption.

    Raised by `_build_diagram` so the orchestrator routes the image through
    its failure handler (fall back to source alt, skip the cache) instead of
    caching a plausible-looking placeholder as if it were a real description.
    """


# Below this length the source alt is too thin to serve as a caption (e.g.
# "Figure 3") — fall through to the marked failure token instead.
_FALLBACK_ALT_MIN_CHARS = 12


def _failure_caption(image_path: Path, original_alt: str) -> str:
    """Caption for an image whose vision call failed or returned an
    unparseable reply. Prefer the figure's authored alt text — a real
    description keeps the figure retrievable; otherwise a clearly-marked
    token that never reads as a genuine caption.
    """
    alt = original_alt.strip()
    if len(alt) >= _FALLBACK_ALT_MIN_CHARS:
        return alt
    return f"Image at {image_path.name} (extraction failed)."


def _build_diagram(image_path: Path, raw_text: str) -> Diagram:
    parsed = _parse_response(raw_text, image_path)
    if parsed.get("parse_failed"):
        raise VisionParseError(f"unparseable vision response for {image_path.name}")
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
    # `parse_failed` tells `_build_diagram` to raise VisionParseError rather
    # than return this placeholder — the caption below is diagnostic only and
    # never reaches output or the cache.
    return {
        "is_diagram": False,
        "diagram_type": None,
        "caption": f"Image at {image_path.name} (description unavailable).",
        "mermaid": None,
        "parse_failed": True,
    }
