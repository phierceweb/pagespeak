"""`pagespeak vision-audit` — flag likely-confabulated vision captions.

Deterministic, $0, no LLM. The vision pass sends each figure to an LLM for a
text caption; that caption is the ONLY thing that makes the figure findable in
a downstream search / RAG index. Occasionally the model writes a confident but
WRONG caption (a squirrel captioned as a lemur, one acid labelled as another) —
coherent prose that a caption-only read never catches.

This flags the suspects cheaply: it compares each generated caption against the
SOURCE alt text the author supplied. When the alt names a clear subject and the
caption keeps NONE of the alt's subject words, the figure is a likely identity
divergence — printed for a human to open the image and adjudicate.

Domain-agnostic: no subject vocabulary, only a generic figure/English filter.
Only figures whose source alt states a clear subject are assessable; figures
without alt (many PDF sources) are skipped, never flagged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ._diagrams import alt_text_by_basename

_MIN_ALT_CHARS = 60  # an alt shorter than this doesn't state a clear subject
_MIN_ANCHOR_CHARS = 4  # a subject-anchor word must be at least this long
_ANCHOR_WINDOW = 18  # anchors come from the alt's leading N tokens
_STEM_LEN = 5  # match an anchor by its leading N chars in the caption
_MAX_SHOWN_PER_DOC = 5

_WORD_RE = re.compile(r"[a-z][a-z\-]{2,}")

# Generic figure-caption filler + English function words, ignored when picking
# an alt's "subject" words. Deliberately generic — NO domain vocabulary.
_GENERIC = frozenset(
    {
        "illustration",
        "illustrated",
        "photograph",
        "photo",
        "diagram",
        "image",
        "images",
        "shows",
        "showing",
        "show",
        "shown",
        "labeled",
        "labelled",
        "cross",
        "section",
        "sectional",
        "view",
        "views",
        "panel",
        "panels",
        "figure",
        "color",
        "colored",
        "colour",
        "close",
        "closeup",
        "detailed",
        "schematic",
        "drawing",
        "depicts",
        "depicting",
        "displays",
        "displaying",
        "display",
        "structure",
        "structures",
        "parts",
        "part",
        "major",
        "human",
        "body",
        "side",
        "left",
        "right",
        "this",
        "that",
        "with",
        "and",
        "the",
        "for",
        "from",
        "into",
        "two",
        "three",
        "four",
        "five",
        "their",
        "which",
        "various",
        "different",
        "between",
        "within",
        "containing",
        "each",
        "where",
        "while",
        "small",
        "large",
        "upper",
        "lower",
        "front",
        "back",
        "inside",
        "outer",
        "inner",
        "top",
        "bottom",
        "middle",
        "center",
        "central",
        "frontal",
        "lateral",
        "horizontal",
        "vertical",
        "magnified",
        "callout",
        "inset",
        "leader",
        "lines",
        "arrows",
        "labels",
        "title",
        "titled",
        "graph",
        "chart",
        "table",
        "comparison",
        "comparing",
        "types",
        "type",
        "process",
        "system",
        "systems",
        "overview",
        "general",
        "complete",
    }
)


@dataclass(frozen=True)
class VisionAuditFinding:
    """One caption flagged as a likely confabulation, for human review."""

    check: str
    image: str
    source_alt: str
    caption: str
    dropped_anchors: tuple[str, ...]


@dataclass(frozen=True)
class VisionAuditReport:
    """Aggregated vision-audit findings for one run."""

    findings_by_doc: dict[Path, list[VisionAuditFinding]]
    docs_scanned: int
    figures_assessed: int

    @property
    def finding_count(self) -> int:
        return sum(len(v) for v in self.findings_by_doc.values())


def _subject_anchors(alt: str) -> list[str]:
    """The alt's leading subject words: content words in its first
    ``_ANCHOR_WINDOW`` tokens, minus generic figure/English filler."""
    toks = _WORD_RE.findall(alt.lower())[:_ANCHOR_WINDOW]
    return [t for t in toks if t not in _GENERIC and len(t) >= _MIN_ANCHOR_CHARS]


def _is_assessable(alt: str) -> bool:
    return len(alt.strip()) >= _MIN_ALT_CHARS and bool(_subject_anchors(alt))


def check_identity_divergence(
    alt_by_basename: dict[str, str], caption_by_basename: dict[str, str]
) -> list[VisionAuditFinding]:
    """Flag each captioned figure whose caption keeps NONE of its source alt's
    subject words. Only figures whose alt states a clear subject are assessed."""
    findings: list[VisionAuditFinding] = []
    for basename, caption in caption_by_basename.items():
        alt = alt_by_basename.get(basename, "").strip()
        if not _is_assessable(alt):
            continue
        anchors = _subject_anchors(alt)
        cap_low = caption.lower()
        if not any(a[:_STEM_LEN] in cap_low for a in anchors):
            findings.append(
                VisionAuditFinding(
                    check="identity_divergence",
                    image=basename,
                    source_alt=alt,
                    caption=caption,
                    dropped_anchors=tuple(anchors[:6]),
                )
            )
    return findings


def _captions_from_cache(cache_dir: Path) -> dict[str, str]:
    """figure basename -> generated caption, from the `.vision-cache` JSONs."""
    captions: dict[str, str] = {}
    for f in sorted(cache_dir.glob("*.json")):
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        caption = entry.get("caption") or ""
        for basename in entry.get("source_paths", []):
            captions[basename] = caption
    return captions


def _source_alts(doc_dir: Path) -> dict[str, str]:
    """figure basename -> author alt text. From the `structured` checkpoint (what
    the vision pass was actually given), falling back to `raw`."""
    checkpoint = next(iter(sorted(doc_dir.glob("*.structured.md"))), None) or next(
        iter(sorted(doc_dir.glob("*.raw.md"))), None
    )
    if checkpoint is None:
        return {}
    return alt_text_by_basename(checkpoint.read_text(encoding="utf-8", errors="replace"))


def _iter_vision_caches(root: Path) -> list[Path]:
    """Every `.vision-cache` dir under root — root's own, or nested ones for a
    fan-out export (one per exam)."""
    if (root / ".vision-cache").is_dir():
        return [root / ".vision-cache"]
    return sorted(p for p in root.rglob(".vision-cache") if p.is_dir())


def audit_vision(paths: list[Path]) -> VisionAuditReport:
    """Scan each path for docs with a `.vision-cache/`, flag divergent captions."""
    findings_by_doc: dict[Path, list[VisionAuditFinding]] = {}
    docs_scanned = 0
    figures_assessed = 0
    for given in paths:
        for cache_dir in _iter_vision_caches(given):
            doc_dir = cache_dir.parent
            docs_scanned += 1
            captions = _captions_from_cache(cache_dir)
            alts = _source_alts(doc_dir)
            figures_assessed += sum(1 for b in captions if _is_assessable(alts.get(b, "")))
            findings = check_identity_divergence(alts, captions)
            if findings:
                findings_by_doc[doc_dir] = findings
    return VisionAuditReport(findings_by_doc, docs_scanned, figures_assessed)


def render_report(report: VisionAuditReport, *, summary_only: bool = False) -> str:
    """Human-readable report: totals, then per-doc candidates (capped)."""
    out = [
        f"vision-audit: {report.docs_scanned} doc(s), "
        f"{report.figures_assessed} figure(s) assessed, "
        f"{report.finding_count} likely-confabulated caption(s) to review"
    ]
    if summary_only:
        return "\n".join(out)
    for doc, findings in report.findings_by_doc.items():
        out.append("")
        out.append(str(doc))
        for f in findings[:_MAX_SHOWN_PER_DOC]:
            out.append(f"  {f.image}  (source names: {', '.join(f.dropped_anchors)})")
            out.append(f"    ALT: {f.source_alt[:120]}")
            out.append(f"    CAP: {f.caption[:120]}")
        hidden = len(findings) - _MAX_SHOWN_PER_DOC
        if hidden > 0:
            out.append(f"  … and {hidden} more in this doc")
    return "\n".join(out)
