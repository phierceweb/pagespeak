"""pagespeak web console — optional FastAPI app over the pipeline.

Install with the ``web`` extra (``pip install -e .[web]`` / ``bin/setup --web``).
Launch in the background with ``bin/start`` (``bin/stop`` / ``bin/restart`` to
manage). Localhost, single-user; no auth.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from pagespeak import __version__
from pagespeak.web._config import load_config
from pagespeak.web._db import init_web_db

_HERE = Path(__file__).parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def create_app(*, start_worker: bool = True) -> FastAPI:
    """Build the configured FastAPI app.

    Args:
        start_worker: Start the in-process conversion worker on startup.
            Tests pass ``False``.
    """
    from pf_core.web.app_factory import create_app as pf_create_app
    from pf_core.web.health import health_router
    from pf_core.web.llm_admin import make_admin_router
    from pf_core.web.templates import setup_templates

    cfg = load_config()
    init_web_db()

    from pagespeak.web._jobs import register_conversion_kind

    register_conversion_kind()

    from pagespeak.web._worker import start_workers, stop_workers

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        handle = start_workers(cfg) if start_worker else None
        try:
            yield
        finally:
            if handle is not None:
                stop_workers(handle)

    _raw: Any = pf_create_app(
        title="pagespeak console",
        version=__version__,
        static_dir=_STATIC,
        log_requests=True,
        rate_limit=False,
        lifespan=lifespan,
    )
    app: FastAPI = _raw
    app.state.cfg = cfg

    templates = setup_templates(app, _TEMPLATES, extra_globals={"app_version": __version__})
    app.state.templates = templates

    app.include_router(health_router())
    # Pass templates=None so the admin uses its own packaged templates dir,
    # which contains dashboard.html, runs_list.html, etc.
    app.include_router(make_admin_router(auth_dep=None, prefix="/admin/llm", templates=None))

    from pagespeak.web.api import actions, pages, partials

    app.include_router(pages.router)
    app.include_router(actions.router)
    app.include_router(partials.router)

    return app
