"""Typer subcommand registration for `pagespeak repair-tables`.

Surgically fixes Marker-broken tables — `<br>`-collapsed mega-cells and split
multi-line-cell tables — in a converted output dir by splicing in the clean grid
Docling extracts from the same PDF page — no
whole-doc re-ingest, no re-vision. See `services/_table_repair.py` and
`docs/audit.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from ..services._table_repair import (
    find_collapsed_cells,
    find_split_tables,
    repair_tables_in_markdown,
)

_SOURCE_MATCH_MIN = 0.6  # fraction of out-dir tokens a PDF must share to auto-match


def _tokens(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _find_source_pdf(stem: str, in_dir: Path = Path("conversions/in")) -> Path | None:
    """Locate the source PDF for an out-dir stem. Exact `<stem>.pdf` first, else
    the `conversions/in/**/*.pdf` sharing the most out-dir tokens — robust to
    naming drift (`device-user-guide` ↔ `Device User Guide v12.2.pdf`,
    `acme-main-manual-14` ↔ `ACME Main Manual 14.0.pdf`)."""
    direct = in_dir / f"{stem}.pdf"
    if direct.exists():
        return direct
    if not in_dir.exists():
        return None
    want = _tokens(stem)
    if not want:
        return None
    best: Path | None = None
    best_score = 0.0
    for p in sorted(in_dir.rglob("*.pdf")):
        score = len(want & _tokens(p.stem)) / len(want)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= _SOURCE_MATCH_MIN else None


def register(app: typer.Typer) -> None:
    """Hang the `repair-tables` subcommand off the given Typer app."""

    @app.command(
        name="repair-tables",
        help=(
            "Repair Marker-broken tables in a converted output dir by splicing "
            "in Docling's clean grid for just the broken-table page(s) — both "
            "`<br>`-collapsed mega-cells AND split multi-line-cell tables. "
            "Patches the <stem>.raw.md checkpoint; re-run "
            "`convert <dir> --from cleanup --vision-cache-only` (matching the "
            "dir's .pagespeak-run.json flags) to propagate the fix to "
            "sections/ at $0. Needs the source PDF (auto-located in "
            "conversions/in/, or pass --source). Read each spliced table by "
            "eye — Docling is a targeted table fix, not uniformly better."
        ),
    )
    def repair_tables_cmd(
        out_dir: Path = typer.Argument(
            ..., exists=True, file_okay=False, dir_okay=True, help="A converted output dir."
        ),
        source: Path | None = typer.Option(
            None, "--source", help="Source PDF (default: auto-locate in conversions/in/)."
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Report what would change without writing."
        ),
    ) -> None:
        raws = sorted(out_dir.glob("*.raw.md"))
        if not raws:
            typer.echo(f"no <stem>.raw.md checkpoint found under {out_dir}", err=True)
            raise typer.Exit(code=1)
        raw = raws[0]
        stem = raw.name[: -len(".raw.md")]
        text = raw.read_text(encoding="utf-8", errors="replace")

        n_collapsed = len(find_collapsed_cells(text))
        n_split = len(find_split_tables(text))
        total = n_collapsed + n_split
        if total == 0:
            typer.echo("no repairable tables found — nothing to repair")
            return

        pdf = source or _find_source_pdf(stem)
        if pdf is None or not pdf.exists():
            typer.echo(
                f"found {total} repairable table(s) but no source PDF for '{stem}'. "
                "Pass --source <pdf> (Docling needs the page).",
                err=True,
            )
            raise typer.Exit(code=1)

        typer.echo(
            f"{n_collapsed} collapsed + {n_split} split table(s) in {raw.name}; "
            f"Docling-splicing from {pdf}…"
        )
        repaired, records = repair_tables_in_markdown(text, str(pdf))
        fixed = sum(1 for r in records if r.status == "repaired")
        for r in records:
            detail = f" ({r.br_count} <br>)" if r.br_count else ""
            typer.echo(f"  line {r.line}{detail}, page {r.page}: {r.status}")

        if dry_run:
            typer.echo(f"\n[dry-run] {fixed}/{len(records)} would be repaired; raw.md not written")
            return
        if fixed == 0:
            typer.echo(
                "\nno tables repaired (no page match / Docling also collapsed) — raw.md unchanged"
            )
            return
        raw.write_text(repaired, encoding="utf-8")
        typer.echo(
            f"\nrepaired {fixed}/{len(records)} table(s) → patched {raw.name}\n"
            f"propagate to sections/ at $0:\n"
            f"  bin/run convert {out_dir} --from cleanup --vision-cache-only "
            f"(add the dir's .pagespeak-run.json split flags)"
        )
