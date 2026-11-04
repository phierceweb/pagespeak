# `pagespeak verify` — PASS or FAIL for a converted document

Check each converted document as a whole, write a PASS/FAIL verdict beside its master, and refuse delivery of a document that fails — read-only apart from the verdict files, $0, no LLM calls.

Do not confuse it with its neighbours: **`pagespeak audit`** reports defect *shapes* (collapsed tables, debris, encoding damage) as warnings and errors, with no verdict and no gate; **`pagespeak baseline diff`** reports what a *code change* altered against a saved run. **`verify`** answers one question per document — is it complete and right enough to hand off — and `deliver` acts on the answer.

For AI assistants: a verdict is only as strong as the checks that ran. Read the "did not run" rows before calling a document done: without its source PDF no source check runs, and without a source map there is no line or picture coverage. Never add a key to the accept list without the maintainer's explicit yes for that finding.

---

## Table of Contents

- [Running it](#running-it)
- [Reading a verdict](#reading-a-verdict)
- [The checks](#the-checks)
- [Accepting a finding](#accepting-a-finding)
- [The source map](#the-source-map)
- [The deliver gate](#the-deliver-gate)
- [Tuning](#tuning)
- [What verify does not do](#what-verify-does-not-do)
- [Adding a new check](#adding-a-new-check)

## Running it

```bash
pagespeak verify conversions/out/<doc>            # one document
pagespeak verify conversions/out/<export>         # every document in an export
pagespeak verify conversions/out/<a> conversions/out/<b>
pagespeak verify conversions/out/<doc> --no-delivery --in-dir path/to/sources
```

It prints one line per document (`PASS` or `FAIL` with the failing checks and counts), the checks that did not run and why, and a total; it exits 1 when any document fails. Each document gets `<doc>/.pagespeak-verdict.md` (for people) and `<doc>/.pagespeak-verdict.json` (for `deliver`). Both are dot-files: `deliver` and `audit` skip them. The source checks read the PDF with pypdfium2, which comes with the `pdf`, `pdf-docling` or `tophat` extra; without it they report `did not run`.

The documents are found the way `deliver` finds them — a folder holding a master `.md`, or a folder of such folders — so verify checks exactly what deliver would hand off. A folder holding two master `.md` files (a backup copy beside the master counts) is refused: one folder gets one verdict. Every path is checked before any verdict is written. The source PDF is the one the source map names while its SHA-256 still matches; otherwise it is looked up under `--in-dir` by the file name and SHA-256 the map or run record holds. A file with the same name but other bytes is not the source. `--in-dir` defaults to the `in` folder beside the document's `out` folder (`conversions/in` for `conversions/out/<doc>`, wherever verify is run from), else `conversions/in`.

## Reading a verdict

Each finding either **fails** the document (lost, duplicated or misplaced content; a picture missing or cut; a picture with no caption) or is a **note** (a quality signal that never blocks). A document passes when no failing finding is left unaccepted.

The verdict file opens with a table of every check: clean, its counts, or `did not run:` with the reason. Then every failing finding with its location and key, every accepted finding with the reason it was accepted, notes (capped per check), and accepted keys that no finding matches any more — a fix has landed, the finding moved, or a newer pagespeak names it differently (re-accept it under its new key).

Locations are `file:line` in the output, or `PDF p<page>` (1-based) with a box in PDF points where the finding is about the source. Keys never contain output line numbers, so a finding keeps its key across rebuilds.

## The checks

| Check | Needs | What fails |
|---|---|---|
| `image_links` | — | a picture file referenced from the master or a section file that does not exist, or that deliver would leave behind: outside the document's `images/` and `sections/`, or a dot-file |
| `orphan_images` | — | a picture the source map says the build cut, that nothing shows (other unused files are notes: the decoration pass leaves files behind) |
| `captions` | vision run | a picture with no vision caption whose own alt text does not describe it ("Figure 6.9 image" is a label and "IMG 2034" a camera's file name; "A photo of a lighthouse at dusk." is a description) |
| `shared_captions` | vision run | identical pictures shown under one cached caption that names the figure or table number of only some of their titles |
| `doubting_captions` | vision run | notes only: a caption that names the description it was given and seems to contradict it (read from its wording, so it never blocks) |
| `split_conservation` | `sections/` | a master line in no section file, a line only the sections hold, or a line the master has once and the sections twice; a heading with a body that no section carries |
| `structure` | — | notes only: skipped heading levels, empty headings, table rows wider than their header |
| `delivery_match` | a delivery folder | a delivered copy that differs from the build (verify only; the gate ignores it) |
| `printed_titles` | source PDF | a printed figure or table title that never arrives, starts more output lines than PDF lines, sits more than a page from its neighbours, or (a figure) has no picture near its caption |
| `outline` | source PDF with bookmarks | notes only: bookmarks no heading carries |
| `line_coverage` | source map | a body line of the PDF (five words or more) that is not in the output near where its neighbours are |
| `line_joins` | source map | two consecutive body lines of one column whose join is not in the output: something moved or was inserted inside a sentence |
| `picture_coverage` | source map | ink left on a page outside every cut picture (dropped art; nearby pieces of one drawing are one finding), ink touching a picture's edge (a crop cut short; every place along the same crops is one finding), or a picture's edge running through a label (a crop showing half of it) |

Rules the checks hold to:

- Do not count alt text as output text in the source checks: after vision the alt is a generated caption, which names a title whether or not the printed one survived. Nor a reference in the text: a printed title counts as arrived where a line starts with it (a label written as a link counts as its text), or where its label is followed by the title's first words, a title of one or two words ending there; only a label the PDF prints bare counts wherever the output names it. Nor a list of figures or tables, in the PDF or the output: a line with dot leaders or a page number in a cell of its own carries no title, nor does one ending in a bare number beside another such line, or whose title is printed again without the number; a caption ending in a number, printed once, stands alone.
- Report a master line the sections lack as a note, not a failure, where a splitter leaves text out on purpose: under a lone `#` title that no section file carries as a heading or breadcrumb, a breadcrumb the splitter cut short included (a quiz splitter's title block), and anywhere in a document split with `--english-only`, which drops non-English branches.
- Read the PDF independently of any build. `_pdf_glyphs` and `_pdf_lines` read pdfium's characters with no layout reasoning beyond lines and columns: a glyph struck twice reads once, the two halves of a ligature both stay, an accent drawn as its own glyph is dropped, sideways text and text its clip path hides are skipped, and a glyph with no Unicode is marked so a match can skip that one word.
- Count each copy in the output once for a line the PDF prints twice on one page, or again after a page without it; a line printed on each page of a run (a table's title over every page it continues on) may share one copy.
- Tolerate exactly one differing word per line: where the line's 4-word runs point, its words are read one by one, and one of them may be missing or spelled differently (a word the build corrected, a ligature the PDF never mapped); a second one loses the line. A line found only by letting that word differ must lie within a thousand output words of where the line before it went, and on no words another line was found on exactly, or it is lost: two lines a word apart need two copies. Spacing differences are tolerated by matching the line's letters run together, and up to two words the output adds inside a line (a label printed over an arrow, set inline) by finding the line's words in order.
- Count a join as kept where one line's last two words and the next line's first two (around a word a hyphen split: the word whole, or both halves with the hyphen kept) stand together beside one more word of either line, or the six words run together letter by letter: four words alone recur elsewhere in a book.
- Check a line the reader joined across table cells cell by cell: a gap far wider than the line's own word spaces parts two cells, though it is narrower than a column gutter. A row whose cells are all under five words is found only where each cell stands whole within 200 output words of where the line before went.
- Skip a join where the first line's row carries on to its right inside its column: the reader cut that line at something it does not read (a step-number badge), so the next line follows the row's end.
- Treat as page furniture, not dropped or cut art, a small drawing (up to an inch across) found on three or more pages, counting copies in the running head and foot and in art left out on purpose, even printed a little larger or smaller, or partly inside a crop (icons, badges) — it is reported once as a note.
- Count as a label a line of up to eight words not set in the document's body face: the font and size (within a quarter point) most of its longer lines are set in, so a document that is mostly figure does not make its labels the body. A crop cuts a label in two when at least 2pt of the label's width and 30% of its height lie inside the crop, and at least 2pt of its width or 30% of its height lie outside it (past a side edge, the top or bottom edge, or both at a corner). A label finding's key names the labels it cuts.

## Accepting a finding

When a finding has been read and the output is right as it is, add its key to `<doc>/.pagespeak-accepted.json`:

```json
{"accepted": [
  {"key": "picture_coverage:cut:p12:100,80,420,360", "why": "a table cell's frame, not art — checked against the page"}
]}
```

A key part longer than 80 characters is cut and ends in `~` and a digest of the whole part, so two long lines that open alike keep apart. Every entry needs a non-empty `why`. An accepted finding stays in the verdict with its reason; it no longer fails the document. A malformed file fails the document (`accepted_list:unreadable:<digest of its bytes>`, as does an unreadable source map) rather than reading as "nothing accepted"; accepting one broken copy accepts no later edit of it. Accept findings one by one, never in bulk to turn a verdict green.

## The source map

Line coverage, line joins and picture coverage need to know what the build read: which pages, the band between running head and foot, where it cut each picture, and what it leaves out on purpose. Only the build that cut the pictures knows that, so it writes `<doc>/.pagespeak-source-map.json` with `write_source_map()` (`services/_source_map.py`; the format is in that module's docstring). No build in this package writes one: `pagespeak convert` output has no map, so these three checks run only on documents from a build that cuts its own pictures and calls `write_source_map()`. Without a map they report `did not run` and the verdict says so.

Do:

- Write one map per build, every time the build runs, beside the master.
- List every picture the build cut, with its page and box in PDF points (origin bottom-left, as pdfium reports them).
- Name what the build drops on purpose — art (`left_out`: page and box) and text (`left_out_text`: a pattern) — each with a reason a reader can check.
- Name art that sits behind text and is not kept as a picture (`background`: an opener photo the build crops one band of, a tinted panel). Its ink is not dropped art, and the text over it is still checked line by line — unlike `left_out`, which exempts both.
- Name fonts whose text layer stores a symbol under a stand-in letter (`glyphs`), so the PDF's text reads as the page shows it.

Do not:

- Put book knowledge into pagespeak code. A per-book exception belongs in that book's map.
- Use `left_out` to silence a finding you have not read. That is what the accept list is for, one finding at a time.

## The deliver gate

`pagespeak deliver` and the web console's Deliver call `services._deliver.deliver()`, which verifies every document under the source first and refuses — naming each failing document's verdict file — while any fails. It reuses a document's last verdict while the document is unchanged: a fingerprint over the master, `sections/` and `images/` (dot-files aside), the run record, the accept list, the source map, the last checkpoint before vision, the vision-cache entries, the bytes of the source PDF verify finds (or that it finds none), `PAGESPEAK_VERIFY_MIN_DROPPED_INK` and the pagespeak version. Any change re-runs verify. The gate ignores `delivery_match`: delivering is how a stale delivery gets fixed.

There is no flag to skip the gate. To hand off a document whose finding is a known, accepted state, accept that finding. Deliver hands off a folder's `sections/` and `images/` only beside its master, leaves dot-files out, and refuses a `sections/`, `images/` or `chunks/` folder given as the source. A source holding no document delivers nothing and leaves the last delivery in place.

`strip_for_delivery()` itself is ungated; library callers that need the gate call `deliver()`.

## Tuning

`PAGESPEAK_VERIFY_MIN_DROPPED_INK` (default `150`): dark pixels, at one pixel per point, that ink away from every picture needs before `picture_coverage` calls it dropped art. Lower it to catch small drawings; raise it when a book's decorative marks trip it. Ink touching a picture's edge is reported from 15 dark pixels, and a long thin mark (at most 6pt tall and 100pt or more wide: a writing line, a table's heavy rule) is never called dropped art.

## What verify does not do

- **It does not judge whether a caption is true.** `doubting_captions` reads what the caption says about its label; `pagespeak vision-audit` compares captions to source alt text. Neither replaces looking at the picture.
- **It does not check a crop for extra content.** A picture that holds part of a neighbouring figure passes picture coverage; only ink outside every picture is checked.
- **It does not see art drawn on a filled panel.** The layout pass paints a filled rectangle out whole, so a drawing on a tinted panel that no crop holds, or that a crop cuts, is not found.
- **It does not see art drawn as a PDF annotation.** Pages are rendered without their annotations, so review markup (highlights, notes) is never called dropped art, and neither is a stamp, an ink drawing or a filled form field.
- **It does not read text set to read upright on a turned page.** A page the PDF turns to show it (`/Rotate`) is read in its own coordinates, where such text runs sideways; line coverage notes the page.
- **It does not replace reading the output.** A PASS means no check found a defect, among the checks that ran.

## Adding a new check

1. Write the check as a function returning a `CheckResult` (`services/_verify_finding.py`), in a `services/_verify_<concern>.py` module with its own test module. Build each finding's key with `finding_key()` from what the defect is — a file name, a page and its text — never from an output line number.
2. Decide what fails and what is a note. Fail only on content lost, duplicated or misplaced, or a picture missing, cut or uncaptioned; everything else is a note.
3. When the check needs something that may be absent (the source PDF, a source map, a vision run), return `CheckResult(check, skipped=<reason>)` instead of passing silently.
4. Call it from `verify_document()` (`services/_verify.py`) or, when it reads the source PDF, from `source_checks()` (`services/_verify_source.py`).
5. Run it read-only across the whole corpus before trusting it, and read what it reports. Fix false alarms in the general rule, never with a per-document exception in code.
6. Add its row to the table above, and the module to `docs/architecture.md`.
