"""Scan ``conversions/in`` + ``conversions/out`` into Conversion records.

A Conversion is keyed on its ``conversions/out/<dir>`` directory and linked
to a source in ``conversions/in`` by the *preserved checkpoint stem*
(``<dir>/<stem>.raw.md`` → ``in/<stem>.<ext>``), so hand-named out dirs
still link. Sources with no out dir appear as "not yet converted". This is
what makes a Finder-drop and a web upload interchangeable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pagespeak.web._config import WebConfig

#: Pipeline phases in order. ``final`` is the consolidated ``<stem>.md``.
PHASES: tuple[str, ...] = (
    "ingest",
    "cleanup",
    "normalize",
    "repair",
    "structure",
    "vision",
    "split",
)

#: Checkpoint suffix per phase (relative to the out dir, stem-prefixed).
_CHECKPOINT_SUFFIX: dict[str, str] = {
    "ingest": ".raw.md",
    "cleanup": ".cleaned.md",
    "normalize": ".normalized.md",
    "repair": ".repaired.md",
    "structure": ".structured.md",
    "vision": ".visioned.md",
}

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}


@dataclass(frozen=True)
class Conversion:
    """A single document workspace (out dir, optionally linked to a source)."""

    dir_name: str
    out_dir: Path
    stem: str | None
    source_path: Path | None
    phases_done: dict[str, bool]
    image_count: int
    has_run_record: bool


def slugify(stem: str) -> str:
    """Lowercase, collapse spaces/underscores/dots to hyphens."""
    s = stem.strip().lower()
    s = re.sub(r"[\s_.]+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "doc"


def _safe_stem(out_dir: Path) -> str | None:
    """Original source stem from the single ``*.raw.md`` checkpoint, or None."""
    raws = sorted(out_dir.glob("*.raw.md"))
    if len(raws) != 1:
        return None
    return raws[0].name[: -len(".raw.md")]


def _find_source(in_dir: Path, stem: str) -> Path | None:
    if not in_dir.is_dir():
        return None
    for f in in_dir.iterdir():
        if f.is_file() and f.stem == stem:
            return f
    for f in in_dir.iterdir():
        if f.is_file() and f.stem.lower() == stem.lower():
            return f
    return None


def _phase_map(out_dir: Path, stem: str | None) -> dict[str, bool]:
    done = {p: False for p in PHASES}
    done["final"] = False
    if stem is not None:
        for phase, suffix in _CHECKPOINT_SUFFIX.items():
            done[phase] = (out_dir / f"{stem}{suffix}").is_file()
        done["final"] = (out_dir / f"{stem}.md").is_file()
    done["split"] = (out_dir / "sections").is_dir()
    return done


def _image_count(out_dir: Path) -> int:
    images = out_dir / "images"
    if not images.is_dir():
        return 0
    return sum(1 for f in images.iterdir() if f.suffix.lower() in _IMAGE_EXTS)


def _build_conversion(cfg: WebConfig, dir_name: str, out_dir: Path) -> Conversion:
    stem = _safe_stem(out_dir)
    source = _find_source(cfg.in_dir, stem) if stem else None
    return Conversion(
        dir_name=dir_name,
        out_dir=out_dir,
        stem=stem,
        source_path=source,
        phases_done=_phase_map(out_dir, stem),
        image_count=_image_count(out_dir),
        has_run_record=(out_dir / ".pagespeak-run.json").is_file(),
    )


def _unconverted(cfg: WebConfig, source: Path) -> Conversion:
    dir_name = slugify(source.stem)
    out_dir = cfg.out_dir / dir_name
    done = {p: False for p in PHASES}
    done["final"] = False
    return Conversion(
        dir_name=dir_name,
        out_dir=out_dir,
        stem=None,
        source_path=source,
        phases_done=done,
        image_count=0,
        has_run_record=False,
    )


def scan_conversions(cfg: WebConfig) -> list[Conversion]:
    """All Conversions: every out dir, plus sources with no out dir yet."""
    out_convs: list[Conversion] = []
    stems_seen: set[str] = set()
    if cfg.out_dir.is_dir():
        for d in sorted(p for p in cfg.out_dir.iterdir() if p.is_dir()):
            conv = _build_conversion(cfg, d.name, d)
            out_convs.append(conv)
            if conv.stem:
                stems_seen.add(conv.stem.lower())

    extra: list[Conversion] = []
    if cfg.in_dir.is_dir():
        for f in sorted(p for p in cfg.in_dir.iterdir()):
            if not f.is_file() or f.name.startswith("."):
                continue
            if f.stem.lower() in stems_seen:
                continue
            extra.append(_unconverted(cfg, f))
    return out_convs + extra


def safe_out_dir(cfg: WebConfig, dir_name: str) -> Path | None:
    """Resolve ``out/<dir_name>``, or ``None`` if it escapes the out root.

    Guards against path traversal: a ``dir_name`` like ``..`` (including
    URL-encoded forms that arrive already-decoded as a path segment) would
    otherwise let a request read or serve files outside ``conversions/out/``.
    """
    root = cfg.out_dir.resolve()
    try:
        candidate = (cfg.out_dir / dir_name).resolve()
    except (OSError, ValueError):
        return None
    if candidate != root and not candidate.is_relative_to(root):
        return None
    return candidate


def get_conversion(cfg: WebConfig, dir_name: str) -> Conversion | None:
    """Return one Conversion by out-dir name, or by an unconverted source slug."""
    out_dir = safe_out_dir(cfg, dir_name)
    if out_dir is None:
        return None
    if out_dir.is_dir():
        return _build_conversion(cfg, dir_name, out_dir)
    for conv in scan_conversions(cfg):
        if conv.dir_name == dir_name:
            return conv
    return None
