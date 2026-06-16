"""POST action routes: upload, run (with cost gate), cancel, retry."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from pagespeak.web._config import WebConfig
from pagespeak.web._cost import gate_decision, vision_will_run
from pagespeak.web._jobs import CONVERSION_KIND, ConversionInputs, ConversionOptions
from pagespeak.web._scan import get_conversion

router = APIRouter(prefix="/api")


@router.post("/upload")
async def upload(request: Request, file: UploadFile) -> Response:
    cfg: WebConfig = request.app.state.cfg
    cfg.in_dir.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "upload").name
    dest = cfg.in_dir / name
    dest.write_bytes(await file.read())
    return RedirectResponse(url="/", status_code=303)


def _str_or_none(v: Any) -> str | None:
    """Convert a form value (str | UploadFile | None) to str | None."""
    if v is None or v == "":
        return None
    return str(v)


def _options_from_form(form: dict[str, Any]) -> ConversionOptions:
    def b(key: str, default: bool = False) -> bool:
        return str(form.get(key, str(default))).lower() in ("1", "true", "on", "yes")

    def s(key: str) -> str | None:
        return _str_or_none(form.get(key))

    diagrams = b("diagrams", True)
    # vision_cache_only requires diagrams (the converter raises otherwise) — drop
    # it if images are skipped, so even a hand-crafted POST can't make that combo.
    cache_only = b("vision_cache_only") and diagrams

    return ConversionOptions(
        preset=s("preset"),
        diagrams=diagrams,
        vision_backend=s("vision_backend"),
        vision_cache_only=cache_only,
        cleanup=s("cleanup"),
        split_sections=b("split_sections"),
        nested_split=b("nested_split"),
        normalize_headings=b("normalize_headings"),
        normalize_headings_mode=s("normalize_headings_mode"),
        normalize_headings_backend=s("normalize_headings_backend"),
        pdf_backend=s("pdf_backend"),
        docx_backend=s("docx_backend"),
        workers=int(form.get("workers") or 1),
        source_type=s("source_type"),
        source_label=s("source_label"),
        rerun_from=s("rerun_from"),
    )


@router.post("/run/{dir_name}")
async def run(request: Request, dir_name: str) -> Response:
    cfg: WebConfig = request.app.state.cfg
    form: dict[str, Any] = dict(await request.form())
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"No conversion {dir_name!r}")

    start: str | None = _str_or_none(form.get("start"))
    stop_after: str | None = _str_or_none(form.get("stop_after"))
    confirmed = str(form.get("confirmed", "")).lower() in ("1", "true", "on", "yes")
    opts = _options_from_form(form)

    if start in (None, "ingest") and conv.source_path is None:
        raise HTTPException(status_code=409, detail="No source file to ingest for this conversion.")

    will_run = vision_will_run(
        start, stop_after, diagrams=opts.diagrams, cache_only=opts.vision_cache_only
    )
    backend = opts.vision_backend or "claude_code"
    decision = gate_decision(
        out_dir=conv.out_dir, will_run=will_run, backend=backend, confirmed=confirmed
    )

    if decision.blocked:
        return HTMLResponse(
            f'<div class="p-3 rounded bg-red-50 text-red-700 text-sm">{decision.message}</div>',
            status_code=200,
        )
    if decision.needs_confirm:
        templates = request.app.state.templates
        resp: Response = templates.TemplateResponse(
            request,
            "partials/cost_preview.html",
            {
                "conv": conv,
                "decision": decision,
                "form": form,
                "start": start,
                "stop_after": stop_after,
            },
        )
        return resp

    from pf_core.jobs import JobRepo

    from pagespeak.web.api.partials import render_job_status

    inputs = ConversionInputs(
        out_dir=str(conv.out_dir),
        source_path=str(conv.source_path) if conv.source_path else None,
        start=start,
        stop_after=stop_after,
        options=opts,
        confirmed_vision=confirmed,
    )
    job_id = JobRepo().create(kind=CONVERSION_KIND, inputs=inputs, created_by="web")
    # Return the live status line into #run-result (it self-polls to running →
    # done/failed). No redirect — the user stays on the page and gets feedback.
    return render_job_status(request, job_id)


@router.post("/deliver/{dir_name}")
async def deliver(request: Request, dir_name: str) -> Response:
    """Strip a converted out dir down to delivery-ready files (master `.md` +
    `sections/` + `images/`) under `conversions/delivery/<dir_name>/`. Returns
    an inline HTMX snippet showing the result, mirroring `pagespeak deliver`."""
    from pagespeak.services._deliver import strip_for_delivery

    cfg: WebConfig = request.app.state.cfg
    conv = get_conversion(cfg, dir_name)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"No conversion {dir_name!r}")
    dest = cfg.delivery_dir / dir_name
    try:
        result = strip_for_delivery(conv.out_dir, dest)
    except (OSError, ValueError) as exc:
        return HTMLResponse(
            f'<div class="p-3 rounded bg-red-50 text-red-700 text-sm">delivery failed: {exc}</div>',
            status_code=200,
        )
    if result.documents == 0:
        return HTMLResponse(
            '<div class="p-3 rounded bg-amber-50 text-amber-800 text-sm">'
            'nothing to deliver — no master <span class="mono">.md</span> in this output yet'
            "</div>",
            status_code=200,
        )
    return HTMLResponse(
        '<div class="p-3 rounded bg-green-50 text-green-800 text-sm">'
        f"delivered {result.documents} document(s), {result.files} file(s) → "
        f'<span class="mono">{result.dest}</span>'
        "</div>",
        status_code=200,
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel(request: Request, job_id: int) -> Response:
    from pf_core.exceptions import PreconditionError
    from pf_core.jobs import JobRepo

    from pagespeak.web._worker import terminate_job

    repo = JobRepo()
    row = repo.get(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such job")
    terminate_job(job_id)
    if row["status"] in ("pending", "running"):
        # The worker may move the job to a terminal state between our read and
        # the cancel — suppress the resulting PreconditionError (no-op, not 409).
        with contextlib.suppress(PreconditionError):
            repo.cancel(job_id, reason="canceled from console")
    return RedirectResponse(url="/", status_code=303)


@router.post("/jobs/{job_id}/retry")
async def retry(request: Request, job_id: int) -> Response:
    from pf_core.jobs import JobRepo

    JobRepo().retry(job_id)
    return RedirectResponse(url="/", status_code=303)
