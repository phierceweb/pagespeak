"""Pipeline manifest: shared state across ingest chunked-worker phases.

The manifest is the single source of truth for what work is done.
Each worker reads it on entry, skips completed work, and updates it
incrementally so an interrupted ingest run can resume from the next call.

File layout under OUTDIR (chunked path):

    manifest.json                     — this module's responsibility
    chunks/<page_range>/raw.md        — _chunk.py writes
    chunks/<page_range>/images/...    — _chunk.py writes
    <stem>.raw.md                     — _ingest.py writes after concat
    images/                           — _ingest.py writes after flatten
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pf_core.log import get_logger
from pf_core.pipeline.run_record import file_sha256 as sha256_file
from pf_core.utils.io import atomic_write_json

logger = get_logger(__name__)

MANIFEST_VERSION = 3
MANIFEST_FILENAME = "manifest.json"

__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "ChunkState",
    "Manifest",
    "VisionState",
    "sha256_file",
]


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ChunkState:
    page_range: str  # e.g. "0-49"
    status: str  # "pending" | "in_progress" | "completed" | "failed"
    raw_md: str | None = None  # relative path under OUTDIR
    images: list[str] = field(default_factory=list)  # relative paths under OUTDIR
    completed_at: str | None = None
    error: str | None = None
    pdf_backend: str | None = None  # "marker" / "docling"


@dataclass
class VisionState:
    backend: str | None = None
    model: str | None = None
    completed_image_phashes: list[str] = field(default_factory=list)
    failed_image_phashes: list[str] = field(default_factory=list)


# Tombstone — retained for legacy callers; not in `__all__`.
@dataclass
class StitchState:
    completed_at: str | None = None
    consolidated_md: str | None = None


@dataclass
class Manifest:
    """Pipeline state. Lives at OUTDIR/manifest.json. Read on every phase entry,
    written incrementally so resume picks up at the next undone unit of work.
    """

    output_dir: Path
    input_path: str = ""
    input_sha256: str = ""
    version: int = MANIFEST_VERSION
    chunks: list[ChunkState] = field(default_factory=list)
    vision: VisionState = field(default_factory=VisionState)

    @classmethod
    def path_for(cls, output_dir: Path) -> Path:
        return output_dir / MANIFEST_FILENAME

    @classmethod
    def load_or_create(
        cls,
        output_dir: Path,
        *,
        input_path: Path | None = None,
    ) -> Manifest:
        """Load an existing manifest from OUTDIR, or initialize a fresh one.

        If `input_path` is given and an existing manifest's `input_sha256`
        doesn't match, raises ValueError — don't silently mix two inputs in
        one output dir.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        mf_path = cls.path_for(output_dir)
        if mf_path.exists():
            data = json.loads(mf_path.read_text(encoding="utf-8"))
            schema_version = data.get("version", 1)
            if schema_version < MANIFEST_VERSION:
                raise ValueError(
                    f"Manifest schema v{schema_version} at {mf_path} predates the "
                    f"current schema (v{MANIFEST_VERSION}), which unified the chunked + "
                    f"single-shot output shape and is incompatible with this manifest. "
                    f"Re-run with --force (discards completed chunks) or "
                    f"`rm -rf {output_dir}` to start fresh."
                )
            mf = cls._from_dict(output_dir, data)
            if input_path is not None:
                expected = sha256_file(input_path)
                if mf.input_sha256 and mf.input_sha256 != expected:
                    raise ValueError(
                        f"Input fingerprint mismatch in {mf_path}: existing manifest "
                        f"was built from a different file (sha256 {mf.input_sha256[:12]}…). "
                        f"Use a fresh output_dir or delete the manifest to start over."
                    )
                # Backfill input metadata if a partial manifest existed without it.
                if not mf.input_sha256:
                    mf.input_sha256 = expected
                    mf.input_path = str(input_path.resolve())
                    mf.save()
            return mf

        mf = cls(output_dir=output_dir)
        if input_path is not None:
            mf.input_path = str(input_path.resolve())
            mf.input_sha256 = sha256_file(input_path)
        mf.save()
        return mf

    @classmethod
    def _from_dict(cls, output_dir: Path, data: dict[str, Any]) -> Manifest:
        chunks = [ChunkState(**c) for c in data.get("chunks", [])]
        vision = VisionState(**data.get("vision", {}))
        return cls(
            output_dir=output_dir,
            input_path=data.get("input_path", ""),
            input_sha256=data.get("input_sha256", ""),
            version=data.get("version", MANIFEST_VERSION),
            chunks=chunks,
            vision=vision,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "chunks": [asdict(c) for c in self.chunks],
            "vision": asdict(self.vision),
        }

    def save(self) -> None:
        """Atomic write: temp file in OUTDIR + rename. Survives crash mid-write."""
        mf_path = self.path_for(self.output_dir)
        mf_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(mf_path, self.to_dict())

    # --- chunk helpers ---

    def chunk_by_range(self, page_range: str) -> ChunkState | None:
        for c in self.chunks:
            if c.page_range == page_range:
                return c
        return None

    def add_or_update_chunk(self, chunk: ChunkState) -> None:
        existing = self.chunk_by_range(chunk.page_range)
        if existing is None:
            self.chunks.append(chunk)
        else:
            idx = self.chunks.index(existing)
            self.chunks[idx] = chunk
        self.save()

    def mark_chunk_completed(
        self,
        page_range: str,
        *,
        raw_md: str,
        images: list[str],
        pdf_backend: str | None = None,
    ) -> None:
        chunk = self.chunk_by_range(page_range)
        if chunk is None:
            chunk = ChunkState(page_range=page_range, status="completed")
            self.chunks.append(chunk)
        chunk.status = "completed"
        chunk.raw_md = raw_md
        chunk.images = images
        chunk.completed_at = _utcnow_iso()
        chunk.error = None
        if pdf_backend is not None:
            chunk.pdf_backend = pdf_backend
        self.save()

    def mark_chunk_failed(self, page_range: str, *, error: str) -> None:
        chunk = self.chunk_by_range(page_range)
        if chunk is None:
            chunk = ChunkState(page_range=page_range, status="failed")
            self.chunks.append(chunk)
        chunk.status = "failed"
        chunk.error = error
        self.save()

    def completed_chunk_ranges(self) -> set[str]:
        return {c.page_range for c in self.chunks if c.status == "completed"}

    def all_chunk_images(self) -> list[Path]:
        """Absolute paths to every image saved across every completed chunk,
        ordered by chunk page-range start then by image filename."""
        out: list[Path] = []
        for chunk in sorted(self.chunks, key=_chunk_sort_key):
            if chunk.status != "completed":
                continue
            for rel in chunk.images:
                out.append(self.output_dir / rel)
        return out

    def all_chunk_raw_md(self) -> list[Path]:
        """Absolute paths to each chunk's raw markdown, ordered by page range."""
        out: list[Path] = []
        for chunk in sorted(self.chunks, key=_chunk_sort_key):
            if chunk.status == "completed" and chunk.raw_md:
                out.append(self.output_dir / chunk.raw_md)
        return out

    # --- vision helpers ---

    def mark_vision_completed(self, phash: str) -> None:
        if phash not in self.vision.completed_image_phashes:
            self.vision.completed_image_phashes.append(phash)
        if phash in self.vision.failed_image_phashes:
            self.vision.failed_image_phashes.remove(phash)
        self.save()

    def mark_vision_failed(self, phash: str) -> None:
        if phash not in self.vision.failed_image_phashes:
            self.vision.failed_image_phashes.append(phash)
        self.save()

    def vision_completed_set(self) -> set[str]:
        return set(self.vision.completed_image_phashes)

    def set_vision_config(self, *, backend: str, model: str | None) -> None:
        self.vision.backend = backend
        self.vision.model = model
        self.save()

    # --- stitch helpers (no-op stubs; the manifest has no stitch block) ---

    def mark_stitch_completed(self, *, consolidated_md: str) -> None:  # noqa: ARG002
        """No-op stub. The manifest carries no stitch block; retained so
        legacy callers stay valid."""


def _chunk_sort_key(chunk: ChunkState) -> tuple[int, str]:
    """Sort chunks by their numeric start page, falling back to string compare."""
    pr = chunk.page_range
    try:
        first = pr.split("-", 1)[0]
        return (int(first), pr)
    except (ValueError, IndexError):
        return (10**9, pr)
