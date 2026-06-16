"""Pagespeak DB configuration — thin wrapper over pf-core's connection helpers.

All LLM call tracking writes to whatever DB the standard `DATABASE_URL`
env var points at — SQLite by default (file in `~/.pagespeak/`),
Postgres or MySQL by setting `DATABASE_URL=postgresql://...` or
`mysql+pymysql://...`. pf-core's SQLAlchemy abstraction handles all
three transparently.

`init_db()` is idempotent: safe to call multiple times. It creates
pf-core's tracking schema (`llm_runs`, `llm_models`, `llm_agent_types`,
`llm_prompts`, `llm_run_payloads`, `llm_run_configs`,
`llm_run_outcomes`, `llm_run_metrics`, plus related tables) if absent.
Pagespeak's CLI entry point calls it once from `cli.main()`.

Tracking is **opt-in for library consumers**: if the calling process
never invokes `init_db()`, `_agent_runtime` checks `_initialized` and
silently skips the `LlmRunRepo` write. Pagespeak still works as a
library; no DB rows are persisted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pf_core.db.connection import (
    get_engine as _pf_get_engine,
)
from pf_core.log import get_logger

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = get_logger(__name__)

# Module-level flag — `_agent_runtime._write_run_row()` checks this
# before attempting any pf-core tracking write. Library consumers that
# never call `init_db()` get tracking-as-no-op for free.
_initialized = False


def _default_sqlite_url() -> str:
    """Return the default SQLite URL pointing at `~/.pagespeak/llm_tracking.db`.

    Override the parent directory via `PAGESPEAK_DB_DEFAULT_DIR` (tests
    set this to a `tmp_path`). The directory is auto-created on first
    call so the first conversion run succeeds without a manual mkdir.
    """
    base = Path(os.environ.get("PAGESPEAK_DB_DEFAULT_DIR") or (Path.home() / ".pagespeak"))
    base.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{base / 'llm_tracking.db'}"


def resolve_db_url() -> str:
    """Resolve the SQLAlchemy connection URL.

    Precedence (highest first):
    1. `DATABASE_URL` env var (any SQLAlchemy URL — sqlite, postgresql,
       mysql+pymysql, etc.)
    2. Default SQLite at `~/.pagespeak/llm_tracking.db` (or
       `$PAGESPEAK_DB_DEFAULT_DIR/llm_tracking.db` when overridden).
    """
    explicit = (os.environ.get("DATABASE_URL") or "").strip()
    if explicit:
        return explicit
    return _default_sqlite_url()


def _redact_db_url(url: str) -> str:
    """Return ``url`` with any password masked, safe for logging.

    A ``DATABASE_URL`` may carry credentials (`postgresql://user:pass@host/db`).
    Logging it verbatim leaks a secret into terminals + log files, so it is
    rendered through SQLAlchemy's URL parser with ``hide_password=True``. On any
    parse failure we return a fixed placeholder rather than risk echoing the raw
    credential — a deliberate fail-safe substitution, not a silently swallowed
    error.
    """
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<redacted>"


def get_engine() -> Engine:
    """Return the SQLAlchemy engine for the configured DB URL.

    Delegates to `pf_core.db.connection.get_engine`, which caches the
    engine per-process. Call `pf_core.db.connection.reset_engine()`
    between tests that switch URLs.
    """
    engine: Engine = _pf_get_engine(resolve_db_url())
    return engine


def init_db() -> None:
    """Create pf-core's tracking schema if absent. Idempotent.

    Called once from `cli.main()` at CLI startup. Library consumers
    that want tracking enabled should call this before their first
    `to_markdown()` invocation. Without it, every LLM call still
    fires correctly — just no DB rows are written.
    """
    global _initialized
    if _initialized:
        return
    from pf_core.llm.tracking import metadata

    engine = get_engine()
    metadata.create_all(engine)
    _initialized = True
    logger.debug("pagespeak_db_initialized url=%s", _redact_db_url(resolve_db_url()))


__all__ = [
    "get_engine",
    "init_db",
    "resolve_db_url",
]
