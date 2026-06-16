"""HTMX fragment routes (queue table / actions form / llm summary)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from pagespeak.utils._phash import compute_phash
from pagespeak.web._config import WebConfig
from pagespeak.web._scan import PHASES, get_conversion, safe_out_dir

router = APIRouter(prefix="/partials")


def _doc_name(job: dict[str, Any]) -> str:
    out = (job.get("inputs") or {}).get("out_dir") or ""
    return Path(out).name


@router.get("/queue", response_class=HTMLResponse)
async def queue(request: Request) -> HTMLResponse:
    from pf_core.jobs import JobRepo

    from pagespeak.web._jobs import CONVERSION_KIND

    repo = JobRepo()
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=6)
    jobs = repo.find(kind=CONVERSION_KIND, since=since, limit=50)
    active = [{**j, "doc": _doc_name(j)} for j in jobs if j["status"] in ("pending", "running")]
    recent = [
        {**j, "doc": _doc_name(j)} for j in jobs if j["status"] not in ("pending", "running")
    ][:10]
    resp: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "partials/queue.html", {"active": active, "recent": recent}
    )
    return resp


@router.get("/actions/{dir_name}", response_class=HTMLResponse)
async def actions(request: Request, dir_name: str) -> HTMLResponse:
    cfg: WebConfig = request.app.state.cfg
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        return HTMLResponse("")
    resp: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "partials/actions.html", {"conv": conv, "phases": list(PHASES)}
    )
    return resp


def render_job_status(request: Request, job_id: int) -> HTMLResponse:
    """Live status line for one job — shared by the run endpoint (initial
    render into #run-result) and the /job/{id} self-poll."""
    from pf_core.jobs import JobRepo

    job = JobRepo().get(job_id)
    if job is None:
        return HTMLResponse("")
    terminal = job["status"] in ("succeeded", "failed", "canceled")
    resp: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "partials/job_status.html",
        {"job": job, "terminal": terminal, "dir_name": _doc_name(job)},
    )
    return resp


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job(request: Request, job_id: int) -> HTMLResponse:
    return render_job_status(request, job_id)


@router.get("/phase-strip/{dir_name}", response_class=HTMLResponse)
async def phase_strip(request: Request, dir_name: str) -> HTMLResponse:
    cfg: WebConfig = request.app.state.cfg
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        return HTMLResponse("")
    resp: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "partials/phase_strip.html", {"conv": conv, "phases": list(PHASES)}
    )
    return resp


def _image_vision(out_dir: Path, name: str) -> dict[str, Any]:
    """Caption + mermaid + diagram_type for one extracted image, read from the
    vision cache by the image's phash (the same key the pipeline writes)."""
    info: dict[str, Any] = {"caption": None, "mermaid": None, "diagram_type": None}
    img = out_dir / "images" / name
    if not img.is_file():
        return info
    try:
        phash = compute_phash(img)
    except Exception:
        return info
    if not phash:
        return info
    from pagespeak.services import _vision_cache

    data = _vision_cache.load(out_dir / ".vision-cache" / f"{phash}.json")
    if data:
        info.update(
            caption=data.get("caption"),
            mermaid=data.get("mermaid"),
            diagram_type=data.get("diagram_type"),
        )
    return info


@router.get("/image/{dir_name}/{name}", response_class=HTMLResponse)
async def image_info(request: Request, dir_name: str, name: str) -> HTMLResponse:
    cfg: WebConfig = request.app.state.cfg
    if "/" in name or "\\" in name or name.startswith("."):
        return HTMLResponse("")
    out_dir = safe_out_dir(cfg, dir_name)
    if out_dir is None:
        return HTMLResponse("")
    info = _image_vision(out_dir, name)
    resp: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "partials/image_detail.html",
        {"dir_name": dir_name, "name": name, **info},
    )
    return resp


@router.get("/llm/{dir_name}", response_class=HTMLResponse)
async def llm(request: Request, dir_name: str) -> HTMLResponse:
    cfg: WebConfig = request.app.state.cfg
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        return HTMLResponse("")

    from pf_core.jobs import JobRepo

    from pagespeak.web._jobs import CONVERSION_KIND

    jobs = JobRepo().find(kind=CONVERSION_KIND, limit=200)
    job_ids = [j["id"] for j in jobs if (j.get("inputs") or {}).get("out_dir") == str(conv.out_dir)]

    total_calls: int = 0
    total_cost: float = 0.0
    for jid in job_ids:
        runs = _runs_for_job(jid)
        total_calls += int(runs["count"])
        total_cost += float(runs["cost"])

    resp: HTMLResponse = request.app.state.templates.TemplateResponse(
        request,
        "partials/llm.html",
        {"conv": conv, "calls": total_calls, "cost": total_cost, "job_ids": job_ids},
    )
    return resp


def _runs_for_job(job_id: int) -> dict[str, float | int]:
    # job_detail's runs_summary aggregates count + total_cost in SQL, so it
    # stays accurate even when a job has thousands of LLM runs (a big vision
    # pass) — unlike summing a capped list_runs() page.
    from pf_core.web.llm_admin.queries import job_detail

    detail = job_detail(job_id) or {}
    summary = detail.get("runs_summary") or {}
    return {"count": int(summary.get("runs") or 0), "cost": float(summary.get("total_cost") or 0.0)}
