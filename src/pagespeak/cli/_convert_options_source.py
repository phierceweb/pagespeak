"""`convert`'s options for what to read and how: the input, backends, cleanup,
decorations, DOCX and QTI switches."""

from __future__ import annotations

from pathlib import Path

import typer

from ._backend_kwargs import HELP as BACKEND_KWARGS_HELP

INPUT_PATH = typer.Argument(..., exists=True, dir_okay=True, readable=True)
OUTPUT_DIR = typer.Option(
    Path("./out"),
    "--output-dir",
    "-o",
    help="Directory for the markdown file and extracted images.",
)
PRESET = typer.Option(
    None,
    "--preset",
    help="Curated config bundle: rag-default | flat | textbook | archival | qti. Per-flag args explicitly passed on the CLI win over preset values. See docs/presets.md.",
)
FORCE_OCR = typer.Option(
    False,
    "--force-ocr/--no-force-ocr",
    help="PDF only: force OCR even on text-bearing PDFs.",
)
DEVICE = typer.Option(
    None,
    "--device",
    help='PDF only: torch device ("cpu" / "mps" / "cuda"). Use "cpu" to dodge the surya/MPS crash on Apple Silicon.',
)
PAGE_RANGE = typer.Option(
    None,
    "--page-range",
    help='PDF only: convert only these pages, 0-based. Spec like "0-19" or "0-3,5,7-9".',
)
HTML_BASE_URL = typer.Option(
    None,
    "--html-base-url",
    help="HTML only: base URL of the source page so relative <img> refs "
    "(e.g. ../Storage/..) download. Example: the page's own URL.",
)
CLEANUP = typer.Option(
    "basic",
    "--cleanup",
    help="Cleanup level: off | basic | aggressive.",
)
CROSS_REFS = typer.Option(
    "keep",
    "--cross-refs",
    help="How to handle \\[label](#page-X-Y) refs: keep | strip | remap.",
)
PDF_BACKEND = typer.Option(
    "marker",
    "--pdf-backend",
    help="PDF backend: 'marker' (default) | 'docling' (requires pagespeak\\[pdf-docling]; pair with --heading-hierarchy, else every heading lands at one level) | 'tophat' (Top Hat quiz-export PDFs → per-question markdown, requires pagespeak\\[tophat]) | 'layout' (a book read from its text layer with its profile, <source>.layout.yaml; requires pagespeak\\[layout]; see docs/layout-backend.md).",
)
HEADING_HIERARCHY = typer.Option(
    False,
    "--heading-hierarchy/--no-heading-hierarchy",
    help="Docling PDF only. Infer real heading levels from PDF bookmarks, then section numbering, then font style, instead of Docling's flat single-level default. Helps documents with an embedded outline or 'Section N.'/'N.M' numbering; not a win on documents with neither. Off by default. Requires docling>=2.109. See docs/backends.md.",
)
PDF_BACKEND_KWARGS = typer.Option(None, "--pdf-backend-kwargs", help=BACKEND_KWARGS_HELP)
DECORATION_THRESHOLD = typer.Option(
    None,
    "--decoration-threshold",
    min=0,
    help="Look-alike pictures that occur at least this many times are page furniture: a near-identical copy is removed, another keeps only its description, unless it is large and used at most twice under its own description. Default 5; 0 turns it off. See docs/pipeline-decorations.md.",
)
DECORATION_HAMMING_DISTANCE = typer.Option(
    None,
    "--decoration-hamming-distance",
    min=0,
    help="How alike pictures must be to count as one piece of furniture, in perceptual-hash bits (default 12). 2 = only near-identical copies: use it for screenshot-heavy help sites whose screens all share one frame.",
)
REPAIR_TABLES = typer.Option(
    False,
    "--repair-tables/--no-repair-tables",
    help="Marker PDF only. After ingest, splice Docling's clean grid over Marker-broken tables — both <br>-collapsed mega-cells (a multi-column table jammed into one cell) and split multi-line-cell tables (one row per wrapped line). Off by default; requires pagespeak\\[pdf-docling]. Same fix as the standalone `pagespeak repair-tables` command, run inline. See docs/repair-tables.md.",
)
DOCX_BACKEND = typer.Option(
    "markitdown",
    "--docx-backend",
    help="DOCX backend: 'markitdown' (default) | 'python-docx' (structure-faithful, requires pagespeak\\[docx-structured]). Ignored for non-.docx formats.",
)
DOCX_OUTLINE_HEADING_DEPTH = typer.Option(
    0,
    "--docx-outline-heading-depth",
    help="python-docx only. Outline→heading switch. 0 (default) = retain the WHOLE Word outline as a nested list (only the document title is '#'). N>0 overrides the top N outline levels into headings (1 = ilvl0 → '#').",
)
STRIP_FRONTMATTER = typer.Option(
    False,
    "--strip-frontmatter/--no-strip-frontmatter",
    help="DOCX only: drop revision-history / instructional-text / Word-TOC frontmatter before the first H1 heading. Off by default; the rag-default / flat / textbook presets enable it.",
)
ANSWER_KEY = typer.Option(
    True,
    "--answer-key/--no-answer-key",
    help="Canvas QTI quiz exports only: mark/state the correct answers. On by default; --no-answer-key renders a blank quiz.",
)
