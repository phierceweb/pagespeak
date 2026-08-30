"""Validator pipeline for the `vision` agent's JSON reply.

Records one signal per call on `llm_run_validations`. Observability only —
`_vision_parse` still builds the `Diagram`, so a failing signal changes nothing.
"""

from __future__ import annotations

from typing import Any

from pf_core.llm.parse import truncated_from_usage
from pf_core.llm.validate import (
    ValidationResult,
    ValidationSignal,
    cross_field_validator,
    has_pipeline,
    parse_and_validate,
    register,
)
from pf_core.log import get_logger

logger = get_logger(__name__)

_VALIDATOR = "vision_response_complete"
_SCHEMA_VERSION = 1


@cross_field_validator(_VALIDATOR)
def _vision_response_complete(parsed: Any, *, context: dict[str, Any]) -> list[ValidationSignal]:
    if not isinstance(parsed, dict):
        return [
            ValidationSignal(_VALIDATOR, "error", passed=False, details={"reason": "not an object"})
        ]

    signals: list[ValidationSignal] = []

    caption = parsed.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        signals.append(
            ValidationSignal(_VALIDATOR, "error", passed=False, details={"reason": "empty caption"})
        )

    if parsed.get("is_diagram"):
        mermaid = parsed.get("mermaid")
        if not isinstance(mermaid, str) or not mermaid.strip():
            signals.append(
                ValidationSignal(
                    _VALIDATOR,
                    "error",
                    passed=False,
                    details={"reason": "is_diagram is true but mermaid is empty"},
                )
            )

    if not signals:
        signals.append(ValidationSignal(_VALIDATOR, "info", passed=True))
    return signals


def ensure_registered() -> None:
    """Idempotent — pf-core's registry is global and tests clear it."""
    if has_pipeline("vision"):
        return
    register("vision", cross_field=[_VALIDATOR], schema_version=_SCHEMA_VERSION)


def validate_vision_response(
    raw_text: str,
    *,
    run_id: int | None = None,
    usage: dict[str, Any] | None = None,
) -> ValidationResult | None:
    """Never raises; None when validation could not run at all."""
    ensure_registered()
    try:
        return parse_and_validate(
            raw_text,
            agent_type="vision",
            run_id=run_id,
            expect="object",
            truncated=truncated_from_usage(usage),
        )
    except Exception as e:  # noqa: BLE001 — observability must never break ingest
        logger.warning("vision_validation_failed error=%r", e)
        return None
