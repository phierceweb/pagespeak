"""`--pdf-backend-kwargs`: backend pipeline options as a JSON object."""

from __future__ import annotations

import json
import math
from typing import Any

import typer

HELP = (
    "PDF backend pipeline options as a JSON object, passed to the backend as-is "
    """(e.g. '{"IgnoreTextProcessor_max_streak": 100000}' for Marker). Recorded in """
    ".pagespeak-run.json; a later `convert` into the same output dir inherits it. "
    "See docs/backends.md."
)


def parse_backend_kwargs(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(
            value,
            parse_constant=_no_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_keys,
        )
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--pdf-backend-kwargs is not valid JSON: {exc.msg}") from exc
    except ValueError as exc:
        raise typer.BadParameter(f"--pdf-backend-kwargs: {exc}") from exc
    except RecursionError as exc:
        raise typer.BadParameter("--pdf-backend-kwargs is nested too deeply") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("--pdf-backend-kwargs must be a JSON object ({...})")
    return parsed


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a number JSON allows")


def _finite_float(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"{text} is too large a number")
    return number


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _v in pairs]
    repeated = sorted({k for k in keys if keys.count(k) > 1})
    if repeated:
        raise ValueError(f"key given twice: {', '.join(repeated)}")
    return dict(pairs)
