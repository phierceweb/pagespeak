"""HTML page routes (home/queue + conversion detail)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.responses import Response

from pagespeak.web._config import WebConfig
from pagespeak.web._scan import (
    PHASES,
    Conversion,
    get_conversion,
    safe_out_dir,
    scan_conversions,
)

router = APIRouter()

# Maps the ?view= phase to its checkpoint file suffix; "final" → "<stem>.md".
_VIEW_SUFFIX = {
    "ingest": ".raw.md",
    "cleanup": ".cleaned.md",
    "normalize": ".normalized.md",
    "repair": ".repaired.md",
    "structure": ".structured.md",
    "vision": ".visioned.md",
    "final": ".md",
}

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}


@router.get("/")
async def home(request: Request) -> Response:
    cfg: WebConfig = request.app.state.cfg
    templates = request.app.state.templates
    conversions = scan_conversions(cfg)
    return cast(
        Response,
        templates.TemplateResponse(request, "pages/home.html", {"conversions": conversions}),
    )


@router.get("/help")
async def help_page(request: Request) -> Response:
    return cast(
        Response,
        request.app.state.templates.TemplateResponse(request, "pages/help.html", {}),
    )


def _checkpoint_path(conv: Conversion, view: str) -> Path | None:
    if conv.stem is None:
        return None
    suffix = _VIEW_SUFFIX.get(view)
    if suffix is None:
        return None
    p = conv.out_dir / f"{conv.stem}{suffix}"
    return p if p.is_file() else None


def _default_view(conv: Conversion) -> str:
    for v in ("final", "vision", "structure", "repair", "normalize", "cleanup", "ingest"):
        if _checkpoint_path(conv, v) is not None:
            return v
    return "final"


@router.get("/c/{dir_name}")
async def detail(request: Request, dir_name: str, view: str | None = None) -> Response:
    cfg: WebConfig = request.app.state.cfg
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"No conversion {dir_name!r}")
    chosen = view or _default_view(conv)
    cp = _checkpoint_path(conv, chosen)
    markdown = cp.read_text(encoding="utf-8") if cp else ""
    run_record = None
    rr = conv.out_dir / ".pagespeak-run.json"
    if rr.is_file():
        try:
            run_record = json.loads(rr.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run_record = None
    images = []
    img_dir = conv.out_dir / "images"
    if img_dir.is_dir():
        images = sorted(f.name for f in img_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTS)
    return cast(
        Response,
        request.app.state.templates.TemplateResponse(
            request,
            "pages/detail.html",
            {
                "conv": conv,
                "stem": conv.stem,
                "phases": list(PHASES),
                "view": chosen,
                "markdown": markdown,
                "images": images,
                "run_record": run_record,
            },
        ),
    )


@router.get("/c/{dir_name}/images/{name}")
async def image(request: Request, dir_name: str, name: str) -> Response:
    cfg: WebConfig = request.app.state.cfg
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=404, detail="not found")
    out_dir = safe_out_dir(cfg, dir_name)  # traversal guard on dir_name
    if out_dir is None:
        raise HTTPException(status_code=404, detail="not found")
    path = out_dir / "images" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)


@router.get("/c/{dir_name}/md/{view}")
async def checkpoint_md(request: Request, dir_name: str, view: str) -> Response:
    """Raw markdown of one checkpoint as text/markdown — fetched by <zero-md>
    to render the preview pane (and reused by the raw-text view)."""
    cfg: WebConfig = request.app.state.cfg
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        raise HTTPException(status_code=404, detail="not found")
    cp = _checkpoint_path(conv, view)
    if cp is None:
        raise HTTPException(status_code=404, detail="not found")
    text = cp.read_text(encoding="utf-8")
    # Rewrite relative image refs to the absolute image route so the renderer
    # (which resolves them against this md URL) loads them, not 404s.
    prefix = f"](/c/{dir_name}/images/"
    text = text.replace("](images/", prefix).replace("](./images/", prefix)
    return PlainTextResponse(text, media_type="text/markdown")
