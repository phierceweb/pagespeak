# Presets and run records

Two ergonomic features:

- **Presets** — named config bundles for common shapes (`rag-default`, `flat`, `textbook`, `archival`, `qti`). One flag instead of six, consistent across maintainers.
- **Run records** — `<output_dir>/.pagespeak-run.json` written after every successful run, capturing the resolved config + input SHA-256
  + timestamps. Re-run drift is a one-line diff between two files.

## Preset catalog

| Preset | Use case | Cleanup | Split | Nested | Min-level | Normalize | Mode | Provenance |
|---|---|---|---|---|---|---|---|---|
| `rag-default` | RAG pipelines, general docs | `basic` | on | on | 2 | on | heuristic | on |
| `flat` | Reference manuals, FAQ | `basic` | on | off | 2 | off | — | off |
| `textbook` | Heavy-hierarchy academic | `aggressive` | on | on | 3 | on | heuristic | off |
| `archival` | Light touch, preserve all | `off` | on | on | 1 | off | — | off |
| `qti` | Canvas quiz exports (one file per quiz) | `off` | on | off | 1 | off | — | own¹ |

¹ `qti` emits its own rich provenance (source_type `exam` + quiz/question fields) via the QTI split path, so the generic `provenance` flag is off for it. The **`provenance`** column controls the generic output frontmatter (source tags + auto-derived `source_label` + per-section breadcrumb locators) — the multi-source RAG enabler. On for `rag-default`; turn it on elsewhere with `--provenance`. See [usage.md](usage.md#tag-a-source-for-a-multi-source-rag-db).

## Usage

### Library

```python
from pagespeak import to_markdown

# Use a preset wholesale.
result = to_markdown("manual.pdf", output_dir="./out", preset="rag-default")

# Use a preset, but override one flag.
result = to_markdown(
    "manual.pdf",
    output_dir="./out",
    preset="textbook",
    split_min_level=4,  # explicit kwarg overrides preset's 3
)
```

### CLI

```bash
# rag-default (split + nested + heuristic normalize)
pagespeak convert manual.pdf -o ./out --preset rag-default

# textbook with one override
pagespeak convert manual.pdf -o ./out \
    --preset textbook \
    --split-min-level 4

# no preset — original to_markdown defaults apply (off, off, basic, etc.)
pagespeak convert manual.pdf -o ./out
```

## Override precedence

For each preset-controlled flag, the resolver picks (in order):

1. **Explicit caller value** — non-`None` library kwarg or command-line flag (detected via Click's `ctx.get_parameter_source(name) == ParameterSource.COMMANDLINE`).
2. **Preset value** — when `preset=` / `--preset` is set.
3. **Recorded run value** — CLI only: re-targeting an output dir that holds a `.pagespeak-run.json` inherits its `resolved_flags` for flags neither passed explicitly nor covered by an explicit `--preset` (`--no-inherit` opts out). See [caching.md](caching.md) § "Re-run flag inheritance".
4. **Original to_markdown default** — `cleanup="basic"`, `split_sections=False`, `nested_split=False`, `split_min_level=None`, `normalize_headings=False`, `normalize_headings_mode="heuristic"`.

Non-preset-controlled flags (`vision_backend`, `vision_model`, `cross_refs`, `pdf_backend`, etc.) aren't affected by presets — they use their own defaults and explicit values (many of them do participate in run-record inheritance; the engine/model flags never do).

## Re-run reproducibility (`<output>/.pagespeak-run.json`)

After every successful run, pagespeak writes `<output_dir>/.pagespeak-run.json`:

```json
{
  "version": "<pagespeak version>",
  "preset": "rag-default",
  "resolved_flags": { /* every flag that influenced the run */ },
  "input": "manual.pdf",
  "input_sha256": "<64 hex chars>",
  "started_at": "<ISO8601>",
  "finished_at": "<ISO8601>",
  "section_count": 360,
  "image_count": 1180
}
```

Two runs against the same input file should produce the same `input_sha256`. Differences in `section_count` / `image_count` / `resolved_flags` between two runs reveal what changed.

The record is also the input to **re-run flag inheritance**: a later `pagespeak convert` into the same output dir defaults unspecified flags to these `resolved_flags`, so re-runs reproduce the original shape without re-typing the flag set. A run whose flags were inherited records them as its own resolved values (with `preset: null` — the concrete flags, not the preset name, carry forward). See [caching.md](caching.md) § "Re-run flag inheritance".

The file is written even when `--no-split-sections` is set — the `section_count` field is `null` in that case.

Failures to write the run record are logged at WARNING and swallowed — a successful conversion shouldn't be killed by an unwritable output directory.

## Adding a new preset

1. Edit `src/pagespeak/services/_presets.py`. Add the new entry to `PRESETS` and extend the `PresetName` literal.
2. Add a row to the catalog table above.
3. Update the `_VALID_PRESETS` tuple in `src/pagespeak/cli/__init__.py`.
4. Pin the new preset's shape in `tests/test_presets.py`.

## Out of scope

- **User-defined presets** in `~/.pagespeak/presets.yaml`. Defer until the built-in five prove the model has legs.
- **Re-run drift detector CLI** — `pagespeak baseline diff` already covers the meaningful drift dimensions (resolved_flags, section set, per-section line counts). See [caching.md](caching.md).
