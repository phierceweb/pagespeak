# The layout backend

Convert a PDF book from its text layer with `--pdf-backend layout`, reading its structure through a per-document profile: fonts mapped to heading levels, ruled tables read from their drawn grid, figures matched to their captions, page furniture dropped.

Not to be confused with the other PDF backends. Marker and Docling infer structure with layout models and need no profile; the `tophat` backend also reads the text layer, but only for Top Hat quiz exports, with fixed rules ([tophat-quizzes.md](tophat-quizzes.md)). Reach for `layout` when a book's structure is plain on the page — consistent faces, ruled tables, numbered captions — but the model-based backends get it wrong, and a profile is worth writing.

---

## Table of Contents

- [When to use it](#when-to-use-it)
- [What it does not read yet](#what-it-does-not-read-yet)
- [The recipe](#the-recipe)
- [What the backend does differently](#what-the-backend-does-differently)
- [The profile](#the-profile)
- [Pictures and the vision cache](#pictures-and-the-vision-cache)
- [Checking a build](#checking-a-build)
- [Adding a book](#adding-a-book)

## When to use it

Use `layout` for a book whose page conventions are regular and nameable: one face for body text, one for headings, captions that start with a fixed word and number, tables drawn as ruled grids, a running head in a fixed band. A profile written once then reads every page the same way, and rebuilding the book is deterministic.

Do not use it for:

- **A document with no profile.** The backend refuses to run without one; it has no defaults to fall back on.
- **A scanned PDF.** It reads the text layer only and never OCRs.
- **A one-off short document.** Writing a profile costs more than fixing a Marker or Docling conversion by hand.

The backend reads the whole book in one pass. `--page-range`, `--max-pages` and chunked ingest (`--workers > 1`) are refused: hyphen joins, tables continued across pages and figure placement all read past a page boundary.

## What it does not read yet

The reader was built on one book design: a single text column, with its running head in a band at the top of the page. On a book outside that design it runs without an error and gets these wrong, so check for them before trusting a build:

- **Two or more text columns.** Lines are read across the full page width, so the columns interleave.
- **A paragraph or a hyphenated word that runs over a page break.** It is split into two paragraphs at the break; only a list item is carried over.
- **A running footer.** Only a bare page number is dropped at the foot of the page (`page_number_below`); other footer text is read as body text unless it is set in a face listed under `fonts.furniture`. `source_map.left_out_text` tells verify about text left out; it removes nothing.
- **A real hyphen at a line end.** Every hyphen that ends a line is taken as a word break and removed, so a compound broken at its own hyphen (`well-` / `known`) comes out as `wellknown`.
- **A sentence that begins like a caption, set right under a picture.** It is taken as that picture's caption. Write `figure_caption` so running text cannot match it (require the full stop after the number).
- **A heading set within about 40 points above a picture.** A line in the heading face that close to the art is read as the picture's label, not as a section heading.
- **Pages with different crop boxes, or a `head_y` above a page's top edge.** The source map holds one body band for the whole book (from the lowest page bottom to `head_y`); where that band does not fit a page, `pagespeak verify` may stop with an error instead of a verdict.
- **Word spaces wider than 7 points.** A gap that wide is read as a column gutter, so in a monospace face from about 10pt (a code listing) each word comes out as a paragraph of its own. Large heads are joined again; running text is not.
- **Text printed outside the visible page.** The whole text layer is read, so text set outside a page's crop box (a printer's slug line, a caption cropped away, text a clipping path hides there) comes into the book. Pictures are cut to the crop box.
- **Measurements fixed in the reader.** A list level is 17 points of indent, lettered steps that run on after a table are `b.` to `h.`, and a crop's file name takes its caption up to the first period (`PLATE 3-1.` fits, `Fig. 3.2` does not).
- **A whole page set sideways.** A rotated page is read in its own coordinates, so its text is read as sideways text (no paragraphs or headings), and a picture is turned upright only when its caption or labels show which way it reads.

`pagespeak verify` catches part of this (a body line that never arrived, a join the page does not make); reading the master against the PDF catches the rest.

## The recipe

Put the profile beside the PDF as `<source stem>.layout.yaml`, then convert:

```bash
bin/run convert "book.pdf" -o conversions/out/book --pdf-backend layout \
  --split-sections --nested-split --split-min-level 2 --provenance --source-type textbook
```

To keep the profile somewhere else, name it in the backend kwargs. The path is recorded in the run record as typed, so a re-run uses it again; a relative path is read from the directory the command runs in, so give an absolute one if later runs start elsewhere:

```bash
bin/run convert "book.pdf" -o conversions/out/book --pdf-backend layout \
  --pdf-backend-kwargs '{"profile": "profiles/book.layout.yaml"}'
```

Install the backend's one dependency with `pip install 'pagespeak[layout]'` (pypdfium2; `[pdf]`, `[pdf-docling]` and `[tophat]` carry it too).

## What the backend does differently

A line shaped like a caption is a caption only when a picture takes it: with no picture above it, it stays ordinary text.

The backend reads structure from the page, so the pipeline treats its output as authored:

- **Its headings are authoritative.** It records `structure_authoritative` and `authored_headings`, so cleanup's heading demotions, heuristic heading normalize and the structure phase's level passes stand down, and the split nests sections by heading level with a leading number (`5.1`, `Chapter 3`) kept in the title ([pipeline-split.md](pipeline-split.md)).
- **Cleanup is off by default.** Cleanup removes converter debris the reader never leaves, and its markdown normalisation changes the reader's output (it re-renders tables and drops the indent that nests lettered sub-steps under their step). An explicit `--cleanup` still runs it.
- **Decorations are off by default** (`decoration_threshold: 0`). The reader leaves page furniture out itself, so every picture it cuts is content; the look-alike pass would turn similar drawings into captions. An explicit `--decoration-threshold` still runs it.

Both defaults are recorded in `.pagespeak-run.json` like any resolved flag, so `--from` and `--rerun-from` keep them, and a library re-run over the output dir (`to_markdown(out, start=…)`) applies them again. They are set before a `--preset` resolves: a preset's cleanup level suits Marker output, not this backend's. They apply to PDF input only.

## The profile

A profile is data, never code: it names the signals a book uses, and the reader in `backends/_layout_*.py` applies them. Do not put a book's wording into the reader; put it in that book's profile. A profile for a licensed book lives beside its source and is never committed.

A whole profile, for the small generated book the tests read (`tests/fixtures/layout_book.py` builds it). Every key shown is required unless its comment says optional:

```yaml
version: 1
bands:            # page geometry, in the PDF's own page coordinates (points, y upward), as `read_page` reports them
  head_y: 740             # text above is the running head; pictures and tables stop below it
  table_rules_below: 740  # rules above (a running head's bars) are not a table
  floor_y: 40             # crops never reach below; a picture wholly below is not cut
  page_number_below: 48   # a bare number below this, outside the inner margins, is a page number
  page_number_inner: [100, 500]
fonts:
  furniture: [Courier]    # faces that are never text (a watermark)
  body: Times             # the running-text face: never a figure label
  heading: Helvetica      # the heading face
  label_head_min_cap: 9   # a heading-face line this tall stops a figure claiming the labels above it
  headings:               # optional (none: no headings). First rule that matches wins; min_cap is the cap height in points; level is 1 to 6
    - {level: 2, caps: true, min_cap: 8, max_len: 70}
    - {level: 3, font_suffix: "-Oblique", min_cap: 8, max_len: 50, no_period: true}
  acute_as_prime: false   # optional. true: an acute accent drawn as its own glyph is a stress mark, read as a prime (false: left as printed)
patterns:                 # regular expressions; '(?!)' never matches: give it to a rule the book does not need
  page_number: '[0-9]{1,3}'
  figure_caption: '^PLATE \d+-\d+\.?'              # the line a picture takes as its caption
  table_title: '^CHART \d+-\d+'                    # a table's title row
  reference_line: '^(CHART|PLATE)\s'               # in a header cell: a line of references, set in parentheses
  reference_run: '(PLATES?|CHARTS?)\s[\d,;\s-]+'   # in a cell: a run of references before a note
  credit: '^Photo:'                                # an art credit line: left out
  cell_credit: '(?!)'                              # a credit printed over a cell's drawing
  cell_credit_fragment: '(?!)'                     # a broken-off piece of one, as a whole line
  label_credit: '(?!)'                             # a credit among a figure's labels
  label_credit_exact: []                           # whole label lines that are pieces of a credit
  note_prefix: '^REMARK:\s*'                       # stripped from a note row above a table's header
  list_mark: '^(•|\d{1,2}\.|[a-z]\.)$'             # a list marker set as a line of its own
  checkbox: "☐"                                    # the tick-box character (any character the book never prints, if it has none)
  instruction: '^Skip this instruction:'           # a line printed over a picture, read before it
  key_entry: '^\d+\.(\s|$)'                        # an entry of a numbered key under a picture
  stops_heading: '## .*\bROUTE\b'                  # under such a heading, bold stops and blanks become a numbered list
  stops_exclude: REVIEW                            # …unless the heading holds this text
  item_heading: '## (CHART |PLATE )'               # table and figure headings: nested under the topic head before them
  aside_heading: SUMMARY                           # a head that is no topic: what follows stays level with it (case-insensitive)
pages: {first: 0, last: 4, skip: [1], flow_charts: []}   # flow_charts: pages that are one chart of boxes and arrows
document:
  opener:                               # a chapter's first page
    text: PART                          # the line that marks it,
    above: 700                          # set above this y,
    font_contains: Bold                 # in a face whose name holds this
    heading: "Part {n}: {title}"        # the chapter heading; {n} counts the openers found
    titles: [First Things]              # one per chapter, in order
    drop_taller_than: 36                # display type dropped on that page: a line taller than this,
    drop_font_suffix: "-Light"          # or one in a face ending so
    drop_min_cap: 30                    # with capitals taller than this
    picture_label: "Part {n} picture"   # names a picture that has no caption
  title_block:                          # the document's opening paragraph
    heading: A Small Book
    cover_page: 0
    keep: '^Second Edition'                 # the cover lines to keep
    lines: [{page: 1, pattern: '^ISBN'}]    # optional: one line from another page, per entry
    # replace: [[old, new]]                 # optional: text swaps in the paragraph
  # Optional, all of them:
  # front_headings: {"PREFACE": "Preface"}         # front-matter lines that are top-level headings before chapter 1
  # drop_lines: [{page: 2, pattern: '^Name:'}]     # lines to leave out on one page
  # group_after_empty_head: true                   # a head followed directly by another head takes every later head in the chapter as its parts
  # raster_tables: {3: {top: 600, figure: [100, 300, 400, 500], label: "Parts, numbered", title: "CHART 1-3. Parts", header: [A, B], rows: [["1", "x"]]}}
  #                                                # a table printed only as a picture, transcribed by hand, keyed by page
  # crop_overrides: {"p0002-plate-1-1.jpeg": [69, 239, 275, 345]}   # a crop's corrected box, by file name
source_map:               # optional
  left_out_text: [['^DRAFT', 'a watermark on every page']]   # text the build drops on purpose, for verify
```

Page numbers in a profile are 0-based. `backends/_layout_profile.py` is the authority on fields and their types.

A profile is read strictly, and the build stops with the field named when:

- the file is not valid YAML, a key is not one the reader knows (a typo is not skipped), a required key is missing, or a value has the wrong type (`furniture: Courier` where a list is wanted);
- `fonts.body`, `fonts.heading`, a `fonts.furniture` entry, `patterns.checkbox`, `patterns.stops_exclude`, the opener's `text`, `heading` or `picture_label`, or the title block's `heading` is empty; or one of the `patterns` (other than `note_prefix`) matches the empty string, which would match every line. The selectors under `document` (`keep`, `lines`, `drop_lines`) may match everything; `drop_lines` leaves out lines of text on the pages read as body, headings included (a dropped heading no longer heads what follows it), never a table's cells, a caption a picture took, or the cover page's lines, which `keep` chooses;
- a pattern does not compile (any regular expression under `patterns`, the `document` selectors, `source_map.left_out_text`), `version` is not the integer 1, or a `raster_tables` entry is not keyed by a page number;
- values cannot work together: `pages.first` below 0 or past `last`, a page named outside `pages.first`–`last`, `floor_y` at or above `head_y`, `page_number_inner` not running left to right, a heading level outside 1–6, the opener's `heading` naming something other than `{n}` and `{title}` or its `picture_label` anything other than `{n}`, a crop or picture box with no area, a transcribed row not as wide as its header;
- `fonts.body` or `fonts.heading` names a face that sets no text on the pages read (the error lists the faces found there);
- a `title_block.lines` entry matches no line on its page, a chapter opener is found past the last listed title, a `flow_charts` page has no caption with a chart above it, a `crop_overrides` name matches no picture, or a crop holds nothing of its page.

A profile whose `pages` run past the PDF's last page is refused when the build opens the PDF.

A profile edit rebuilds on the next `convert` of the PDF that runs ingest (a plain run, or `--rerun-from`): the saved text is reused only while it is newer than both the PDF and its profile. A run that starts later (`--from <phase>`, on the PDF or on the output folder) and any run over the output folder work from the text already read and do not look at the profile.

## Pictures and the vision cache

The backend cuts every picture itself: each crop is rendered at twice the page's scale and saved as JPEG, turned upright when the figure is printed sideways, and named from its page and caption (`p0012-plate-3-1.jpeg` for a figure on the thirteenth page: the page is 0-based, in four digits; a picture with no caption takes the opener's `picture_label`). The vision cache is keyed by each picture's perceptual hash, so a rebuild that cuts the same crops gets every caption from the cache.

Rebuild with the pypdfium2 that made the cache. pdfium renders a little differently from version to version: under pypdfium2 5 a few crops cut on 4.30 hash a couple of bits apart and miss the cache, which keys on the exact hash. Run `--vision-cache-only` on a rebuild to be sure no caption is bought; a miss then shows as a skipped picture, not a call.

A crop that cuts its art short is fixed in the profile's `crop_overrides`, not by recaptioning: an override changes the crop's box, and only that picture's caption is new.

## Checking a build

The backend writes `.pagespeak-source-map.json` beside the master: the pages it read, its body band, every crop's box as cut (never past the page's edge), and what it leaves out on purpose. `pagespeak verify` reads it, so every build gets line coverage, line joins and picture coverage against the source PDF ([verify.md](verify.md)). Do not call a profile done until verify passes on the whole book and the whole master has been read.

## Adding a book

1. Read the book's conventions off its pages: the body and heading faces and their cap heights (`backends/_layout_pages.read_page` on a few pages gives each line's `font` and `h`), the caption and table-title wording, the running-head band, the pages that are covers, contents or flow charts.
2. Write `<source stem>.layout.yaml` beside the PDF, starting from the profile in `tests/fixtures/layout_book.py`.
3. Convert with `--diagrams` off (or `--vision-cache-only`) and read the whole master against the PDF; fix the profile, not the output.
4. Run `pagespeak verify` and fix what it finds through the profile (crop overrides, left-out text) before any vision run.
5. A layout feature the reader does not have yet (a box style, a table shape) belongs in `backends/_layout_*.py` with a generated-PDF test, never as a special case for one book; rebuild every book that uses the backend afterwards and compare its master byte for byte.
