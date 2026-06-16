# Canvas Quiz Conversion (QTI)

Convert a Canvas **Classic Quizzes** export (IMS Common Cartridge + QTI 1.2) into LLM-friendly markdown — one file per quiz, with the correct answers marked.

This is distinct from the document pipeline (PDF/DOCX/…). Those formats are extracted/OCR'd and may need cleanup, heading-normalize, and vision. A QTI export is already *structured data*: the backend reads the quiz structure directly from the XML, so cleanup and heading-normalize are off by default and the only LLM cost is the optional vision pass on referenced figures.

---

## Table of Contents

- [What it converts](#what-it-converts)
- [How to run it](#how-to-run-it)
- [Output shape](#output-shape)
- [Question types](#question-types)
- [Figures and cost](#figures-and-cost)
- [How it fits the pipeline](#how-it-fits-the-pipeline)
- [Boundaries](#boundaries)
- [Adding a new question type](#adding-a-new-question-type)

## What it converts

The input is a Canvas **Classic Quizzes** export — the structure Canvas emits for every classic-quiz QTI export, not anything course-specific. Accept either form:

- an **unzipped export directory** containing `imsmanifest.xml`, or
- the **`.imscc` / `.zip`** archive Canvas downloads (unzipped to a temp dir automatically).

Everything is **manifest-driven**: the quizzes and the media set are discovered from `imsmanifest.xml`, never hardcoded. The number of quizzes, the hash-named folders, and the figure files vary per export and are all read from the manifest.

Detection is structural — `backends/_qti.is_qti_export()` returns True for a directory containing `imsmanifest.xml` or a `.imscc`/`.zip` containing one. `to_markdown()` checks this **before** directory-input ("resume from output dir") mode, so an export folder is never mistaken for an output dir.

## How to run it

CLI — point `convert` at the export directory or the `.imscc`. Per-quiz files are produced for any QTI input; the `qti` preset just turns off the (irrelevant) cleanup/normalize passes:

```bash
pagespeak convert biol-2420-quiz-export/ -o ./out --preset qti
# or the archive form:
pagespeak convert course.imscc -o ./out --preset qti
```

See [presets.md](presets.md) for the `qti` preset.

Web console — upload the `.imscc` and pick the `qti` preset. (Browsers upload files, so use the `.imscc`, not the unzipped folder.)

Do **not** run vision unless you mean to: the vision LLM is **off by default** for QTI even though `--diagrams` defaults on elsewhere (see [Figures and cost](#figures-and-cost)). Pass `--diagrams` explicitly to opt in.

## Output shape

The export **fans out into one independent full-pipeline document per exam**. Each quiz is converted like any other document — its own dir with every pipeline stage checkpoint, its own images, and its own per-question split:

```
conversions/out/<export>/
└── <Exam Title>/
    ├── <Exam Title>.raw.md … .visioned.md   # every stage checkpoint
    ├── <Exam Title>.md                        # whole-exam master doc
    ├── images/                                # only this exam's figures
    ├── sections/                              # the per-question split
    │   ├── Question 001.md                    #   one self-contained Q+A each
    │   ├── …
    │   └── INDEX.md
    ├── .vision-cache/                         # independent per exam
    └── .pagespeak-run.json
```

Because each exam is a standalone document, every stage is restartable per exam (`--from` / `--rerun-from` on `<export>/<Exam>/`). Point QMD (or any RAG ingester) at one `<Exam>/sections/` for a per-exam collection of question-chunks, or at the export dir for one "all exams" collection.

**Provenance frontmatter** gives the strong linkage that makes either collection scheme work. The master doc carries `course` (auto-pulled from the manifest) / `exam` / `quiz_id` (the stable Canvas resource hash) / `points_possible` / `question_count`; each `sections/Question NNN.md` carries `course` / `exam` / `quiz_id` + `question_number` / `question_type` / `points`. `source_type` defaults to `quiz`, `source_label` to the course (both overridable via `--source-type` / `--source-label`).

Inside each doc the exam title is the only `#` H1 and each question is a `## Question N` heading — edit-friendly (the master can be the author's source; a re-render renumbers 1..N and re-splits cleanly) and chunkable per question with no custom parsing. Each question states its answer twice — a `✓` on the option *and* a `**Correct answer:**` line. Pass `--no-answer-key` (CLI) / `answer_key=False` (library) for a blank quiz. `INDEX.md` is written by default (suppressible).

## Question types

The seven Canvas types seen in real exports each map to a faithful rendering with a recoverable answer key: multiple-choice and true/false (one correct option), multiple-answers (all correct marked), matching (a two-column item→match table), short-answer / fill-in-the-blank (accepted-answer list), fill-in-multiple-blanks (per-blank answers), and essay (prompt only — manually graded).

Correct answers come from each item's `<resprocessing>`: a `<varequal>` that is **not** wrapped in `<not>` is a correct selection. For multiple-answers, the `<not>`-wrapped options are the distractors and are excluded.

Any **unknown** type (a New Quizzes item, numerical, multiple-dropdowns) is not dropped: the stem and any choices render, and a `qti_unknown_question_type` WARNING names it.

## Figures and cost

Figures referenced by `$IMS-CC-FILEBASE$` tokens are copied into each exam's own `<exam>/images/` (link-safe-renamed, so spaces/parens in Canvas filenames can't break a `![](…)` link) and linked with their alt text — deterministic and $0. Canvas equation-images carry their LaTeX (`data-equation-content`); they become inline `$…$`, never broken image links.

Running the vision LLM on the figures is **opt-in**: the CLI disables diagrams for a QTI input unless `--diagrams` is passed explicitly, so an ordinary `convert <export>` never silently spends quota on ~dozens of figures. When you do opt in, the vision pass and its phash cache are the same ones the rest of the pipeline uses.

## How it fits the pipeline

`to_markdown` detects a QTI export and delegates to the **fan-out orchestrator** (`orchestrators/_qti_export.run_qti_export`) instead of running a single pipeline. The orchestrator enumerates the quizzes and, per exam: (1) **ingest** — `convert_qti_exam` renders one exam's markdown + copies only the figures it references → `<exam>/<stem>.raw.md` + `images/`; (2) runs the **standard Phase-3 pipeline** over that exam dir via a dir-mode `to_markdown` call (cleanup → vision; per-exam checkpoints, run record, `.vision-cache/`); (3) writes the **master doc** with provenance frontmatter; (4) **splits** it into per-question docs (`split_quiz_into_questions`) under the exam's `sections/`. So each exam reuses the heavy pipeline machinery unchanged. The generic section splitter is not used (the per-question split is QTI-specific). `pagespeak ingest <export>` rejects QTI — use `convert`.

Module layout: `backends/_qti.py` (discovery `enumerate_quizzes`, per-exam ingest `convert_qti_exam`, per-question `split_quiz_into_questions`), `backends/_qti_parse.py` (XML → normalized model), `backends/_qti_render.py` (model → markdown), `models/_quiz.py` (the normalized model), `utils/_html.py` (reusable inline-HTML→markdown cleaner), and `orchestrators/_qti_export.py` (the fan-out). See [architecture.md](architecture.md).

## Boundaries

- **Canvas New Quizzes** (the newer engine) exports a different structure; this backend does not parse it. A future adapter would swap the dialect layer (the QTI structural parser stays).
- **Other LMSs** (Blackboard / Moodle / D2L) use QTI with their own metadata conventions — same skeleton, different type/answer encoding; also a future adapter.
- This is conversion only. Creating Canvas quizzes *from* markdown is a separate tool's job (e.g. `text2qti`).

## Adding a new question type

1. Extend `backends/_qti_parse._parse_item` with an `elif` branch for the new `question_type`, populating the right field on `QuizQuestion` (a new field on `models/_quiz` if the shape doesn't fit `options` / `matches` / `blanks` / `accepted`).
2. Extend `backends/_qti_render._render_body` with the matching branch.
3. Add a parse test (one inline `<item>` fixture) and a render test, built from a real example in an actual export — never an invented shape.
4. Validate by reading the rendered output of a real export, not just the new test.
