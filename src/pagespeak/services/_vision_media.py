"""Image media-type lookup shared by the API vision backends.

Shared so the Anthropic backend (`_vision_backends.py`) and the
OpenRouter backend (`_vision_backend_openrouter.py`) can both reach it without
an import cycle. Self-contained: stdlib only.
"""

from __future__ import annotations

from pathlib import Path

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "image/png")
