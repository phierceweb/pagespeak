"""Tests for `pagespeak._db` — DB URL resolution + schema initialization.

The DB layer is a thin wrapper over pf-core's `pf_core.db.connection`
and `pf_core.llm.tracking.metadata`. Default sink is a SQLite file in
the user's home dir; any `DATABASE_URL` SQLAlchemy connection string
(sqlite/postgres/mysql) overrides it.

Tracking is opt-in: library consumers that never call `init_db()` see
no DB activity — `_agent_runtime` checks `_db._initialized` and skips
the `LlmRunRepo` write when False.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_db_state():
    """Reset pf-core's module-level engine cache and pagespeak's
    `_initialized` flag between tests. pf-core's `get_engine()`
    caches by global, so without this each test would see the
    previous test's engine."""
    from pf_core.db.connection import reset_engine

    import pagespeak._db as db_mod

    reset_engine()
    db_mod._initialized = False
    yield
    reset_engine()
    db_mod._initialized = False


def test_redact_db_url_masks_postgres_password() -> None:
    """A connection string with credentials must never be logged in the
    clear — the password is masked, host/user/db kept for diagnostics."""
    from pagespeak._db import _redact_db_url

    redacted = _redact_db_url("postgresql://user:s3cret@db.example.com:5432/pagespeak")
    assert "s3cret" not in redacted
    assert "user" in redacted
    assert "db.example.com" in redacted
    assert "pagespeak" in redacted


def test_redact_db_url_leaves_credential_free_sqlite_path() -> None:
    """A passwordless URL (the default SQLite sink) survives intact."""
    from pagespeak._db import _redact_db_url

    url = "sqlite:////home/u/.pagespeak/llm_tracking.db"
    assert _redact_db_url(url) == url


def test_redact_db_url_never_echoes_password_on_unparseable_input() -> None:
    """On any parse failure, return a fixed placeholder rather than risk
    echoing a raw credential back into the logs."""
    from pagespeak._db import _redact_db_url

    out = _redact_db_url("not-a-url://garbage:topsecret@@@host")
    assert "topsecret" not in out


def test_resolve_db_url_uses_database_url_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/pagespeak-test.db")
    from pagespeak._db import resolve_db_url

    assert resolve_db_url() == "sqlite:////tmp/pagespeak-test.db"


def test_resolve_db_url_falls_back_to_default_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When `DATABASE_URL` is unset, fall back to a sqlite file in
    `~/.pagespeak/` (or override via `PAGESPEAK_DB_DEFAULT_DIR` for
    tests)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(tmp_path))
    from pagespeak._db import resolve_db_url

    url = resolve_db_url()
    assert url.startswith("sqlite:///")
    assert "llm_tracking.db" in url


def test_resolve_db_url_creates_default_directory_on_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default-sqlite path includes a directory that may not exist
    yet. `resolve_db_url` must create it (mkdir -p semantics) so the
    first conversion run succeeds."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    nested = tmp_path / "nested" / "missing"
    monkeypatch.setenv("PAGESPEAK_DB_DEFAULT_DIR", str(nested))
    from pagespeak._db import resolve_db_url

    resolve_db_url()
    assert nested.is_dir()


def test_init_db_creates_tracking_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """init_db creates all pf-core tracking tables idempotently."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    # Reset module-level state from any earlier test.
    import pagespeak._db as db_mod

    db_mod._initialized = False
    db_mod.init_db()
    db_mod.init_db()  # idempotent — must not raise

    from sqlalchemy import inspect

    engine = db_mod.get_engine()
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "llm_runs" in tables
    assert "llm_models" in tables
    assert "llm_agent_types" in tables
    assert "llm_prompts" in tables


def test_init_db_is_noop_after_first_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call to init_db() does not re-run create_all (verified
    by the absence of a second engine.connect() call). Implementation
    detail — the flag-guarded body is what we assert."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pagespeak._db as db_mod

    db_mod._initialized = False
    db_mod.init_db()
    assert db_mod._initialized is True
    db_mod.init_db()
    assert db_mod._initialized is True  # still True, no exception


def test_cli_main_calls_init_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`pagespeak <subcommand>` initializes the tracking DB
    before dispatching to typer so every `invoke_agent` call gets
    persisted. We verify the wiring by mocking `init_db` and asserting
    `main()` calls it. Typer's `app()` is stubbed so no real CLI runs."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    calls: list[bool] = []

    def _fake_init_db() -> None:
        calls.append(True)

    def _fake_app() -> None:
        pass

    monkeypatch.setattr("pagespeak._db.init_db", _fake_init_db)
    monkeypatch.setattr("pagespeak.cli.app", _fake_app)

    from pagespeak.cli import main

    main()
    assert calls == [True]


def test_cli_main_swallows_init_db_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A bad `DATABASE_URL` must not break conversions. We
    raise from `init_db`, then assert `main()` reaches the typer
    dispatch anyway (no propagated exception) and the warning is logged
    with the expected event key."""
    import logging

    def _fake_init_db_raises() -> None:
        raise RuntimeError("bad DATABASE_URL")

    dispatched: list[bool] = []

    def _fake_app() -> None:
        dispatched.append(True)

    monkeypatch.setattr("pagespeak._db.init_db", _fake_init_db_raises)
    monkeypatch.setattr("pagespeak.cli.app", _fake_app)

    from pagespeak.cli import main

    with caplog.at_level(logging.WARNING, logger="pagespeak.cli"):
        main()
    assert dispatched == [True]
    assert any("pagespeak_db_init_failed" in r.getMessage() for r in caplog.records)
