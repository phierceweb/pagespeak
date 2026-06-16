"""The ``pagespeak_convert`` job kind + its validated input/output schemas.

One job = one ``pagespeak convert`` subprocess covering a phase slice
(``start``..``stop_after``). The worker reads these inputs to build the
command; progress is read from on-disk checkpoints by the scanner.
"""

from __future__ import annotations

from pf_core.jobs import register_kind
from pydantic import BaseModel, Field, field_validator

CONVERSION_KIND = "pagespeak_convert"

_PHASES = ("ingest", "cleanup", "normalize", "repair", "structure", "vision", "split")


class ConversionOptions(BaseModel):
    """The subset of ``convert`` flags the console exposes."""

    preset: str | None = None
    diagrams: bool = True
    vision_backend: str | None = None
    vision_cache_only: bool = False
    cleanup: str | None = None
    split_sections: bool = False
    nested_split: bool = False
    normalize_headings: bool = False
    normalize_headings_mode: str | None = None
    normalize_headings_backend: str | None = None
    pdf_backend: str | None = None
    docx_backend: str | None = None
    workers: int = 1
    source_type: str | None = None
    source_label: str | None = None
    rerun_from: str | None = None


class ConversionInputs(BaseModel):
    """Job inputs: which workspace, which phase slice, which options."""

    out_dir: str
    source_path: str | None = None
    start: str | None = None
    stop_after: str | None = None
    options: ConversionOptions = Field(default_factory=ConversionOptions)
    confirmed_vision: bool = False

    @field_validator("start", "stop_after")
    @classmethod
    def _valid_phase(cls, v: str | None) -> str | None:
        if v is not None and v not in _PHASES:
            raise ValueError(f"phase must be one of {_PHASES}; got {v!r}")
        return v


class ConversionOutputs(BaseModel):
    """Job outputs recorded on success (provenance only — the UI reads the
    Conversion's on-disk checkpoints/images for display, not these fields)."""

    phases: str = ""
    returncode: int = 0


def register_conversion_kind() -> None:
    """Register the kind. Idempotent (safe to call at every import/startup)."""
    register_kind(
        kind=CONVERSION_KIND,
        description="Convert one document (a phase slice of the pipeline).",
        inputs_schema=ConversionInputs,
        outputs_schema=ConversionOutputs,
        default_priority=50,
    )
