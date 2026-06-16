# Contributing to pagespeak

Thanks for your interest. pagespeak turns documents into LLM-friendly Markdown;
contributions that keep it correct, well-tested, and documented are welcome.

## Scope — read this first

pagespeak is a **general** converter. Its readers derive structure from the file
format itself — a Word file's outline levels and heading styles, a PDF's
extracted layout — never from guessing at the meaning or wording of the content.
No corpus-specific phrase lists or content heuristics: a messy source should
yield faithful (if messy) output, not output silently edited to a guess.
Cleaning up a *converter artifact* (e.g. a PDF backend promoting a page header to
a heading) is in scope and is diagnosis-gated; editorial "fixing" of an author's
prose is not.

## Development setup

Python 3.11+ is required.

```bash
git clone https://github.com/phierceweb/pagespeak
cd pagespeak
bin/setup --all          # venv + editable install + every optional extra
```

`bin/setup --all` installs every extra (PDF/Marker, Docling, python-docx, web),
which the full test suite needs. For lighter work, plain `bin/setup` installs the
markitdown-only core; tests that need a missing extra skip cleanly.

## Before you open a pull request

Both gates run in CI — run them locally first:

```bash
bin/test                 # full suite, must be green
bin/lint                 # ruff + mypy (strict) + the file-size guard
```

And hold the change to these standards:

- **Tests travel with code.** New behavior needs tests; a bug fix needs a
  regression test that fails before your change and passes after. One test
  module per source module.
- **Docs travel with code.** A change to the public API, a CLI flag, an env var,
  or a supported format is incomplete without the matching `docs/*.md` +
  `README.md` update.
- **File-size gate.** Python files over 500 lines fail the build; over 300 warn.
  Split by concern (`_<concern>.py`) rather than growing a monolith.

## Coding conventions

The essentials:

- Modern Python 3.11+ syntax — `X | None`, lowercase `dict`/`list`/`tuple`,
  `from __future__ import annotations`.
- Type hints on every public signature; Google-style docstrings on public APIs.
- Structured logging via `pf_core.log.get_logger(__name__)` — never a bare
  `print` outside the CLI layer.
- Catch specific exceptions; never `except Exception: pass`.
- LLM-facing prompts are versioned YAML under `src/pagespeak/prompts/` — bump the
  version on every material edit.

## Versioning

Stability lives in **tags**. `main` may contain unreleased work — pin to a tagged
release for production use. Pre-1.0: a minor bump (`0.X.0`) may include breaking
changes (called out in `CHANGELOG.md`); a patch bump (`0.0.X`) is fixes only.

## Questions

Open an issue for bugs and feature requests.
