"""Public result types returned by `to_markdown()` and the diagram pass.

These are intentionally plain frozen dataclasses so consumers can pickle them,
diff them, or feed them to downstream pipelines without depending on pagespeak
internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Diagram:
    """One image's vision-pass result.

    Returned in `IngestResult.diagrams` and emitted as a Mermaid block
    alongside the image's markdown reference (see README for the embedded
    output shape).

    Attributes:
        image_path: Where the extracted image lives on disk (under
            `<output_dir>/images/`).
        caption: 1-5 sentence description of what the image shows. Lands
            in the image's alt-text in the final markdown — readable by
            screen readers, retrievable without parsing prose. Tier varies
            by image type: data charts get 2-5 sentences (axes, units,
            labels, conclusion), diagrams 1-3 sentences, photos/screenshots/
            logos 1 sentence. See `docs/diagrams.md` for the full prompt.
        mermaid: Valid Mermaid source for diagram-shaped images
            (flowcharts, sequence diagrams, class diagrams, etc.), or
            `None` for photos/screenshots/logos where Mermaid wouldn't
            add information.
        diagram_type: Free-form short tag identifying the diagram shape
            (e.g. `"flowchart"`, `"sequence"`, `"bar-chart"`, or
            `"photo"`). `None` if the vision pass couldn't classify.
    """

    image_path: Path
    caption: str
    mermaid: str | None
    diagram_type: str | None = None


@dataclass
class IngestResult:
    """Output of a single `to_markdown()` call.

    Attributes:
        markdown: The final rendered markdown, with Mermaid blocks
            embedded for any diagram-shaped images. Also written to
            `<output_dir>/<stem>.md`.
        images: Absolute paths to every image extracted from the source,
            in the order they appear in the markdown. Each path lives
            under `<output_dir>/images/`.
        diagrams: One `Diagram` per image that the vision pass examined.
            Length matches `images` when `diagrams=True` was passed; empty
            when diagram extraction was disabled.
        source_format: Detected file extension (e.g. `"pdf"`, `"docx"`)
            for the input. Useful for branching on source-type in
            downstream consumers without re-sniffing the original path.
    """

    markdown: str
    images: list[Path] = field(default_factory=list)
    diagrams: list[Diagram] = field(default_factory=list)
    source_format: str = ""
