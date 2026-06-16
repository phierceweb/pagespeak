# Top Hat Quiz Conversion (`--pdf-backend tophat`)

Convert a **Top Hat quiz export** (the print-to-PDF an instructor downloads from a Top Hat module) into LLM-friendly markdown — one `## Question N` block per question, so the section splitter writes one file per question.

This is a special-purpose PDF backend, not the generic Marker/Docling path. It exists because Top Hat's web-print PDFs are hostile to layout extraction: both Marker and Docling damage them. The `tophat` backend ignores layout entirely and reads the PDF text layer, which is clean.

> **Answer key depends on the export.** If you export *before* the due date the answers aren't populated (the "Show Correct Answer" toggle is collapsed) and the PDF has no answers — the backend renders questions + options only. If you export *after* the due date, the correct option is revealed and the backend marks it (see [Answer key](#answer-key) below) — including fill-in-the-blank answers, which render on an `**Answer:**` line. (The [Canvas QTI](canvas-quizzes.md) path always emits a marked key because QTI carries the answers as data.)

---

## Table of Contents

- [Why Marker and Docling fail](#why-marker-and-docling-fail)
- [How to run it](#how-to-run-it)
- [Output shape](#output-shape)
- [Frontmatter](#frontmatter)
- [Answer key](#answer-key)
- [Figures (image questions)](#figures-image-questions)
- [What it strips](#what-it-strips)
- [Boundaries](#boundaries)

## Why Marker and Docling fail

A Top Hat export renders each question as a multi-column answer card (the option letters in one column, text in another, with "Show Correct Answer / Show Responses" controls in the header). That column structure breaks table detection in both ML backends:

- **Marker** keeps every word but shreds each option into a one-word-per-line table cell (`the<br>first<br>option`), and the only headings it detects are the junk "Video" placeholder blocks — so the splitter cuts on *those*, not the questions.
- **Docling** de-shreds the options but **drops whole questions** (stems and first options) and triple-duplicates the rest across the answer-card columns.

The PDF's underlying **text layer**, however, is pristine in reading order — every `Question N` marker, every stem, every option, no shredding, no drops. So the `tophat` backend extracts the text layer (via `pypdfium2`, no torch/ML), strips the web chrome, and promotes each `Question N` marker to a `## Question N` heading.

## How to run it

```bash
pagespeak convert "Sample_Quiz_2 (53m) _ Top Hat.pdf" -o ./out \
    --pdf-backend tophat --preset rag-default
```

- `--pdf-backend tophat` selects the text-layer backend.
- `--preset rag-default` gives basic cleanup + per-section split (one file per `## Question N`).
- **Leave vision on** (don't pass `--no-diagrams`) so embedded figures get captioned — some questions ARE a diagram (see [Figures](#figures-image-questions)). Vision defaults to the `claude_code` backend ($0; ~1 call per figure, ~a few per quiz) and is phash-cached, so re-runs are free. Use `--no-diagrams` only if you want a pure-text, zero-LLM run (figures are still extracted and referenced, just not captioned).
- No `--normalize-headings-mode llm_full` needed: the headings are already a clean `# quiz` + `## Question N` hierarchy.

Install the light extra if you don't already have a PDF extra:

```bash
pip install pagespeak[tophat]      # just pypdfium2 (also bundled in pdf / pdf-docling)
```

Library API:

```python
from pagespeak import to_markdown

to_markdown("quiz.pdf", output_dir="./out", pdf_backend="tophat",
            preset="rag-default")  # diagrams=True (default) captions figures
```

## Output shape

```
out/
├── <quiz>.md                       # master: frontmatter + # title + ## Question N blocks
├── <quiz>.raw.md … .visioned.md    # stage checkpoints (normal pipeline)
├── images/                         # extracted figures (q<N>_<seq>.png)
└── sections/
    ├── INDEX.md
    ├── Question 001.md             # one file per question, with frontmatter
    ├── Question 002.md
    └── …
```

Per-question files are flat and zero-padded (`Question 001.md`) — the same layout as the [Canvas exams](canvas-quizzes.md), and each carries provenance frontmatter (see [Frontmatter](#frontmatter)). The quiz title is the only `#` H1, so the splitter cuts one file per `## Question N`. Long options that wrap across PDF lines are rejoined; options split across a page break (by an interleaved "Video" block) are recovered.

Master (`<quiz>.md`):

```markdown
---
source_type: "quiz"
source_file: "Sample_Quiz_2 (53m) _ Top Hat.pdf"
quiz: "Sample_Quiz_2 (53m)"
quiz_id: "sample-quiz-2-53m"
question_count: 5
---

# Sample_Quiz_2 (53m)

_5 questions_

> Module 9: Sample Module Page 2:

## Question 1

_Multiple choice_

Which of the following is correct?

- A) the first option
…
```

## Frontmatter

Quiz output carries YAML provenance frontmatter so QMD (or any RAG store) can filter quiz questions by source, quiz, or type. It is **generated by the backend** — there is no post-hoc inject step, and every future quiz gets it automatically. Each `sections/Question NNN.md`:

```yaml
---
source_type: "quiz"
quiz: "Sample_Quiz_2 (53m)"
quiz_id: "sample-quiz-2-53m"
question_number: 1
question_type: "Multiple choice"   # Multiple choice | Multiple answers | Fill in the blank | Image
---
```

- All fields are **derived** — `quiz`/`quiz_id` from the doc title, `question_number` from the heading, `question_type` inferred from the question shape. Nothing is fabricated.
- **Deliberately omitted:** `course`, `assessment_type` (not in the export — pass `--source-label` if you want a label), and `points` (Top Hat's print export carries no per-question points; a guessed `"1 pt"` would be wrong). Canvas exams keep `points` because QTI provides it as real data.
- Quizzes (`source_type: "quiz"`) and exams (`source_type: "exam"`) share one schema and the same splitter (`backends/_qti_split`), so you can filter across both. Exams add `course` and `points` from the QTI manifest.

## Answer key

When the export was taken after the due date, the correct option is revealed — but Top Hat marks it **only visually** (the correct option's letter glyph is rendered light grey with a green check; there is no textual "correct answer" string in the PDF). The backend recovers this deterministically: pdfium exposes each glyph's fill color, and the correct letter is a true grey (`r == g == b`, e.g. `171,171,171`) while every other option letter is faintly blue (`60,67,83`). The grey letters are bucketed under their question and the renderer marks them:

```markdown
## Question 1

Which of the following is correct?

- A) the first option
- B) the second option
- C) the third option
- D) all of the above
- E) A and B ✓

**Correct answer:** E. A and B
```

This is the same shape as the Canvas QTI answer key. It is **deterministic, $0, and offline** — no vision/LLM. Details:

- **Multiple-correct ("select all")** questions mark every correct option and use a plural `**Correct answers:**` line.
- **Fill-in-the-blank** answers are *not* a grey letter — instead Top Hat lists the answer value(s) followed by `blankN`/`BlankN` placeholder-label lines. The backend lifts out the answer(s), drops the labels, and renders an `**Answer:**` (or `**Answers:**`) line; a trailing blank gap in the stem is marked `______`.
- **Discussion prompts** (a "Question N" with no answer toggle) are not gradable and carry no answer.
- The renderer **never fabricates** an answer: a question with no detected correct letter simply has no answer line.

## Figures (image questions)

Some Top Hat questions ARE a figure — a diagram is the whole question (e.g. a multi-stage signaling cascade), with no text stem and no answer toggle. The backend extracts the embedded figure bitmaps from the PDF (recursing into the form XObjects where Top Hat nests them), writes them to `<out>/images/`, references them in the relevant question, and lets the **vision pass** caption them — so an image-only question becomes a captioned (and, for diagrams, Mermaid'd) block:

The `## Question 1` block then holds the figure reference with a vision caption as alt text — `![Signaling cascade showing the flow from an upstream trigger through intermediate stages to downstream targets, with negative-feedback loops…](images/q1_1.png)` — followed by a generated Mermaid `flowchart` of the diagram where the vision pass produced one.

How figures bind to questions:

- A figure binds to its question **by page**, not by pixel position: Top Hat nests figures in form XObjects that report *form-local* coordinates (a top far outside the page), so a figure's y is not comparable to the page text. It binds to the last question marker on its page or an earlier page — which is its question, since a figure sits between its own marker and the next.
- A **bare** marker (no answer toggle) is kept as a question **only when it carries a figure** (a real image question). A bare marker with no figure is a discussion prompt and is dropped.
- Figures bind to ordinary gradable questions too (a question with both a diagram and options).
- Small images (UI chrome — the chat-bubble icon, logos) are filtered by a minimum-size threshold.

Cost: vision is one call per figure on the default `claude_code` backend ($0), and phash-cached, so re-runs are free. A whole course of quizzes is typically a few dozen figures.

## What it strips

The backend drops Top Hat web-print chrome so it never becomes content or a false heading:

- the "Using AI for Learning" banner and "Learn More" link,
- the repeated **Video** / "Please visit the textbook on a web or mobile device…" placeholders,
- the bare "Responses" / "Closed" UI tokens,
- the "Show Correct Answer / Show Responses" controls on each question marker line.

The "Exported for … GMT" line is preserved as a provenance subtitle.

## Boundaries

- **Answer key only when populated** — a before-due-date export has no answers in the PDF (see [Answer key](#answer-key)); the backend then renders questions only. It never guesses.
- **Fill-in-the-blank stems may have an unmarked internal gap** — the answer value(s) are extracted onto an `**Answer:**` line and the `blankN` labels dropped, but a blank *inside* the sentence (not at the end) can't be located from the text, so the stem reads with a missing word there (the answer line still names it).
- **Figures are extracted, video is not** — embedded image figures are pulled out and captioned (see [Figures](#figures-image-questions)). The "Video" blocks are placeholders (not images) and are stripped; a purely video-based question with no figure and no options is dropped.
- **Truncated exports** — a print-to-PDF can clip the quiz if the web page wasn't fully rendered (lazy-loaded questions). The backend converts faithfully what is *in* the PDF; it can't recover questions the export omitted. Verify the PDF has every question before trusting the output.
- **Detection** — the backend is opt-in via `--pdf-backend tophat`. It validates the PDF has gradable markers (a number before `(Show|Hide) Correct Answer` — both `Section 2 Question 1 Hide Correct Answer` and the no-"Question" `Topic 2 Hide Correct Answer` styles) and errors with a clear message if you point it at an ordinary PDF (use `marker`/`docling` for those).
