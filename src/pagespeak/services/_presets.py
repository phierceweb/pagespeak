"""Curated config presets for `to_markdown` / `pagespeak convert`.

A preset is a named bundle of cleanup level + splitter flags + normalize
mode chosen for a specific use case. Presets keep the command line short
("`--preset rag-default`") and make re-runs reproducible across machines.

The library entry point is `resolve_preset(name) -> Preset`. The CLI
entry point lives in `cli/_convert.py`; explicit per-flag overrides on
the command line win over preset values (detected via Click's parameter
source so a default-equal explicit pass still counts as user-set).

Adding a new preset: extend `PRESETS`, document it in `docs/presets.md`,
and capture a regression baseline (file count on a couple of representative
documents) before relying on it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from ._cleanup import CleanupLevel
from ._heading_normalize import NormalizeMode

PresetName = Literal["rag-default", "flat", "textbook", "archival", "qti"]


@dataclass(frozen=True)
class Preset:
    """A named bundle of pagespeak conversion flags.

    Frozen so a preset can't be mutated by accident at call time. All
    fields map 1:1 to `to_markdown` keyword arguments.
    """

    name: PresetName
    cleanup: CleanupLevel
    split_sections: bool
    nested_split: bool
    split_min_level: int | None
    normalize_headings: bool
    normalize_headings_mode: NormalizeMode
    strip_frontmatter: bool
    provenance: bool

    def to_dict(self) -> dict[str, object]:
        """Serializable representation, used by `_run_record` to stamp the
        resolved flags into `<output>/.pagespeak-run.json`."""
        return dict(asdict(self))


PRESETS: dict[PresetName, Preset] = {
    "rag-default": Preset(
        name="rag-default",
        cleanup="basic",
        split_sections=True,
        nested_split=True,
        split_min_level=2,
        normalize_headings=True,
        normalize_headings_mode="heuristic",
        strip_frontmatter=True,
        # The multi-source RAG enabler: stamp every section + the master doc
        # with provenance frontmatter (source tags + auto-derived label +
        # breadcrumb locators). On only for rag-default; other presets stay
        # frontmatter-free unless the caller opts in with --provenance.
        provenance=True,
    ),
    "flat": Preset(
        # Reference manuals, FAQ-shaped content. No nested folders, no
        # heading normalize — keep the doc as-extracted.
        name="flat",
        cleanup="basic",
        split_sections=True,
        nested_split=False,
        split_min_level=2,
        normalize_headings=False,
        normalize_headings_mode="heuristic",
        strip_frontmatter=True,
        provenance=False,
    ),
    "textbook": Preset(
        # Heavy-hierarchy academic docs with `Chapter N` shapes. Aggressive
        # cleanup (drops decoration images, page-anchor spans), heuristic
        # normalize for the structural pattern, deep nesting from L3+.
        name="textbook",
        cleanup="aggressive",
        split_sections=True,
        nested_split=True,
        split_min_level=3,
        normalize_headings=True,
        normalize_headings_mode="heuristic",
        strip_frontmatter=True,
        provenance=False,
    ),
    "archival": Preset(
        # Light-touch: preserve everything, minimal restructuring. For
        # consumers who want the raw extracted shape with nesting only,
        # no cleanup or heading rewrites. Frontmatter preserved.
        name="archival",
        cleanup="off",
        split_sections=True,
        nested_split=True,
        split_min_level=1,
        normalize_headings=False,
        normalize_headings_mode="heuristic",
        strip_frontmatter=False,
        provenance=False,
    ),
    "qti": Preset(
        # Canvas QTI quiz exports. The QTI backend already emits clean
        # markdown (quiz title = the only heading; questions are bold
        # blocks), so cleanup is off and heading-normalize is irrelevant.
        # The per-quiz files are written flat in the output root by the QTI
        # finalizer (not the generic section splitter), so split_sections
        # is off here.
        name="qti",
        cleanup="off",
        split_sections=False,
        nested_split=False,
        split_min_level=1,
        normalize_headings=False,
        normalize_headings_mode="heuristic",
        strip_frontmatter=False,
        # QTI exports carry their own rich provenance (source_type "exam" +
        # quiz/question fields) via the QTI split path, not the generic
        # frontmatter — so the generic provenance flag stays off here.
        provenance=False,
    ),
}


def resolve_preset(name: str) -> Preset:
    """Look up a preset by name. Raises `ValueError` with a helpful list
    of valid presets when `name` is unknown."""
    if name not in PRESETS:
        valid = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(f"unknown preset {name!r}; valid options: {valid}")
    return PRESETS[name]
