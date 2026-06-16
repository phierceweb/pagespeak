"""Top Hat quiz text-layer lines → `TopHatQuiz` model.

Pure text parsing (no PDF / pypdfium2): strip the web chrome, segment on
question markers, and split each question into stem + lettered options. The
answer key (`_tophat_answers`) and figures (`_tophat_images`) are looked up by
the caller and threaded in via `parse_quiz`'s `answers` / `images` maps.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._tophat import TopHatQuestion, TopHatQuiz

# --- chrome / marker patterns -------------------------------------------------

# Short UI tokens that appear as their OWN line. Matched exactly so they never
# substring-match the question-marker line (which ends "... Show Responses").
_JUNK_EXACT = frozenset(
    {
        "Using AI for Learning",
        "Learn More",
        "Responses",
        "Reply",
        "Video",
        "Closed",
        "course.",
    }
)
# Longer chrome phrases, matched as substrings (unambiguous).
_JUNK_SUBSTR = (
    "Use this free, assignable",
    "Please visit the textbook",
    "mobile device to view video",
)
_EXPORTED_RE = re.compile(r"^Exported for .*GMT$")

# Trailing instructor-footer boilerplate Top Hat appends AFTER the last
# question ("WANT TO WORK AHEAD? … HERE'S THE PLAYLIST!", "PLAYLIST FOR THIS
# TOPIC."). It's always at the very end and spans several lines, so we truncate
# at the FIRST sentinel — dropping it and everything after — rather than
# per-line (which would orphan continuation lines like "your notes." into the
# preceding option). Matched case-insensitively as substrings.
_FOOTER_SENTINELS = (
    "WANT TO WORK AHEAD",
    "WATCH THE REMAINING LECTURE",
    "PLAYLIST FOR THIS",
    "HERE'S THE PLAYLIST",
)


def _is_footer_start(line: str) -> bool:
    up = line.upper()
    return any(sentinel in up for sentinel in _FOOTER_SENTINELS)


# Gradable question marker: the question number is the integer immediately
# before "(Show|Hide) Correct Answer". This is format-agnostic — it handles both
# Top Hat marker styles:
#   "Section 2 Question 1 Hide Correct Answer Show Responses"  → 1
#   "Topic 2 Hide Correct Answer Show Responses"               → 2  (no "Question")
# The verb is "Show" on a questions-only export, "Hide" once answers populate.
_CORRECT_ANSWER_RE = re.compile(r"(\d+)\s+(?:Show|Hide)\s+Correct\s+Answer", re.IGNORECASE)
# Bare marker fallback (no answer toggle): "… Question N" heads a figure or
# discussion prompt in the "Question"-word family. (The no-"Question" family's
# bare markers can't be anchored, but its figure questions are gradable.)
_QUESTION_WORD_RE = re.compile(r"\bQuestion\s+(\d+)\b", re.IGNORECASE)


def _marker_number(line: str) -> int | None:
    """The question number if `line` is a question marker, else None.

    Prefers the gradable signal (number before "(Show|Hide) Correct Answer"),
    falling back to a bare "Question N" marker (figure/discussion prompts in
    the Question-word family)."""
    m = _CORRECT_ANSWER_RE.search(line)
    if m:
        return int(m.group(1))
    m2 = _QUESTION_WORD_RE.search(line)
    if m2:
        return int(m2.group(1))
    return None


def _is_gradable_marker(line: str) -> bool:
    """True if `line` is a gradable marker (has an answer toggle)."""
    return _CORRECT_ANSWER_RE.search(line) is not None


# An answer option: a single A-H letter inline with its text
# (`A the first option`) or a lone letter whose text wraps after it.
_OPTION_RE = re.compile(r"^([A-H])\s+(\S.*)$")
_LONE_LETTER_RE = re.compile(r"^([A-H])$")
# Fill-in-the-blank artifacts. Top Hat marks blanks with `blankN`/`BlankN`
# tokens: a PURE-label line is all such tokens (`blank1 blank2`, `Blank1
# Blank2`); the tokens can also appear INLINE in the question template
# (`blank2 blank1 extends hand at wrist…`).
_BLANK_TOKEN_RE = re.compile(r"^[Bb]lank\d+$")  # whole-token (pure-label test)
_BLANK_INLINE_RE = re.compile(r"[Bb]lank\d+")  # anywhere (inline-template test)
_SENT_END_RE = re.compile(r"[.?:]$")

# Subtitle lines (module / page / topic) carry the quiz's real title context;
# these substrings mark instruction/boilerplate lines to keep OUT of it.
_SUBTITLE_EXCLUDE = (
    "guided lecture",
    "open book",
    "change your",
    "answers to the questions",
    "Watch the videos",
    "DISCUSSION",
    "Post questions",
    "NOT A REQUIRED",
    "respond with",
)


def _is_junk(line: str) -> bool:
    if line in _JUNK_EXACT:
        return True
    if _EXPORTED_RE.match(line):
        return True
    return any(sub in line for sub in _JUNK_SUBSTR)


def strip_chrome(lines: list[str]) -> list[str]:
    """Drop Top Hat web-print chrome, keeping question/stem/option lines.

    Removes the AI banner, "Video" placeholder blocks, and bare UI tokens.
    The question-marker line survives because it is matched only by exact
    short tokens (it merely *contains* "Show Responses", never equals it).
    Truncates at the first trailing-footer sentinel (everything from the
    instructor "work ahead / playlist" boilerplate to the end is dropped).
    """
    out: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if _is_footer_start(s):
            break  # trailing instructor footer — drop it and all that follows
        if _is_junk(s):
            continue
        out.append(s)
    return out


def looks_like_tophat(lines: list[str]) -> bool:
    """True if any line is a gradable `… N (Show|Hide) Correct Answer` marker."""
    return any(_is_gradable_marker(ln) for ln in lines)


def is_tophat_pdf(path: Path) -> bool:
    """True if `path` is a Top Hat quiz export (has gradable question markers)."""
    from ._tophat import extract_lines

    return looks_like_tophat(extract_lines(path))


def _is_blank_label_line(line: str) -> bool:
    """True for a PURE Top Hat blank-label line (every token is `blankN`)."""
    tokens = line.split()
    return bool(tokens) and all(_BLANK_TOKEN_RE.match(t) for t in tokens)


def _parse_fitb(body: list[str]) -> tuple[str, tuple[str, ...]] | None:
    """Parse a fill-in-the-blank question's body into (stem, answers), or None.

    Returns None when there are no pure `blankN`/`BlankN` label lines (so the
    question isn't FITB). Top Hat's FITB export has two layouts:

      A: stem sentence → answer value(s) → pure-label lines.
      B: stem instruction → a template line with INLINE `blankN` tokens
         (`blank2 blank1 extends…`) → pure-label line → answer value.

    Both are handled uniformly: pure-label lines are dropped; the stem is the
    leading lines through the first sentence-ending line; among the remaining
    lines, those with inline `blankN` tokens are template (folded into the stem
    with the tokens shown as ``______``) and those without are the answers.
    A trailing blank gap (`is .`) is also marked ``______``.
    """
    if not any(_is_blank_label_line(ln) for ln in body):
        return None
    content = [ln for ln in body if not _is_blank_label_line(ln)]
    if not content:
        return "", ()
    stem_end = next(
        (i for i, ln in enumerate(content) if _SENT_END_RE.search(ln.strip())),
        len(content) - 1,
    )
    rest = content[stem_end + 1 :]
    template = [ln for ln in rest if _BLANK_INLINE_RE.search(ln)]
    answers = tuple(ln.strip() for ln in rest if ln.strip() and not _BLANK_INLINE_RE.search(ln))
    stem = " ".join(content[: stem_end + 1] + template).strip()
    stem = _BLANK_INLINE_RE.sub("______", stem)  # inline blanks → visible gaps
    stem = re.sub(r"\s+([.?])", r" ______\1", stem)  # trailing-gap marker
    return stem, answers


def _option_run(body: list[str]) -> dict[int, tuple[str, str]]:
    """Find the real answer-option lines among `body`, keyed by line index.

    An option line is either inline (`A the first option`) or a lone
    letter (`A`) whose text wraps onto following lines. The catch: a stem can
    *start* with a capital letter + space ("A patient presents…"), which looks
    identical to an inline option. Real options always run in sequence
    A, B, C, …; a stem's stray leading letter does not continue that sequence.

    So we walk the candidate letter lines tracking the next expected letter,
    and reset the run whenever a fresh `A` appears — the earlier (stray) match
    falls back to stem. Returns ``{line_index: (letter, inline_text)}`` for the
    lines that are genuine options.
    """
    candidates: dict[int, tuple[str, str]] = {}
    for i, line in enumerate(body):
        inline = _OPTION_RE.match(line)
        if inline:
            candidates[i] = (inline.group(1), inline.group(2))
        elif _LONE_LETTER_RE.match(line):
            candidates[i] = (line, "")

    run: list[int] = []
    expected = "A"
    for i in sorted(candidates):
        letter = candidates[i][0]
        if letter == expected:
            run.append(i)
            expected = chr(ord(expected) + 1)
        elif letter == "A":  # a fresh A — the prior partial run was a stray stem letter
            run = [i]
            expected = "B"
    return {i: candidates[i] for i in run}


def _parse_options(body: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """Split a question's body lines into (stem, options).

    Lines before the first real option form the stem. Each real option's text
    is its inline text plus any following non-option lines (Top Hat wraps long
    options — and whole multi-line options — across PDF lines). A question with
    no option run (fill-in-the-blank, discussion) returns all body as the stem.
    """
    options_at = _option_run(body)
    if not options_at:
        return " ".join(body).strip(), []
    first = min(options_at)
    options: list[tuple[str, str]] = []
    for i in range(first, len(body)):
        if i in options_at:
            options.append(options_at[i])
        elif options:  # wrapped continuation of the last option's text
            letter, text = options[-1]
            options[-1] = (letter, f"{text} {body[i]}".strip())
    return " ".join(body[:first]).strip(), options


def _parse_header(head: list[str]) -> tuple[str, str | None]:
    """From the lines before the first question marker, derive (title, subtitle).

    The subtitle is the Module / topic / Page block that sits between the quiz
    title and the first instruction line. We stop at the first instruction or
    discussion-blurb line so that boilerplate (`DO:`, the study-guide link, the
    optional discussion paragraph) never leaks into the subtitle.
    """
    if not head:
        return "Quiz", None
    title = head[0]
    subtitle_bits: list[str] = []
    for ln in head[1:]:
        if ln.startswith("DO:") or any(ex in ln for ex in _SUBTITLE_EXCLUDE):
            break
        subtitle_bits.append(ln)
    subtitle = " ".join(subtitle_bits).strip() or None
    return title, subtitle


def parse_quiz(
    lines: list[str],
    answers: dict[int, list[str]] | None = None,
    images: dict[int, list[str]] | None = None,
) -> TopHatQuiz:
    """Parse raw text-layer lines into a `TopHatQuiz`.

    `answers` (from `_tophat_answers.extract_correct_answers`) maps a question
    number to its correct option letter(s). `images` (from
    `_tophat_images.extract_question_images`) maps a question number to its
    figure paths. Both default to empty.

    Segmentation uses the *loose* marker (gradable or bare), so figure questions
    — whose marker has no answer toggle — are seen. A bare question is kept only
    when it carries a figure; a bare marker with neither answers nor an image
    (a pure discussion prompt) is dropped.
    """
    answers = answers or {}
    images = images or {}
    exported = next((ln.strip() for ln in lines if _EXPORTED_RE.match(ln.strip())), None)
    clean = strip_chrome(lines)
    marker_idx = [i for i, ln in enumerate(clean) if _marker_number(ln) is not None]
    title, subtitle = _parse_header(clean[: marker_idx[0]] if marker_idx else clean)

    questions: list[TopHatQuestion] = []
    bounds = marker_idx + [len(clean)]
    for k in range(len(marker_idx)):
        seg = clean[bounds[k] : bounds[k + 1]]
        number = _marker_number(seg[0])
        assert number is not None  # marker_idx only holds marker lines
        gradable = _is_gradable_marker(seg[0])
        imgs = tuple(images.get(number, ()))
        if not gradable and not imgs:
            continue  # bare discussion marker with no figure → not a question
        body = seg[1:]
        fitb = _parse_fitb(body)
        if fitb is not None:
            stem, blanks = fitb
            options: list[tuple[str, str]] = []
        else:
            stem, options = _parse_options(body)
            blanks = ()
        questions.append(
            TopHatQuestion(
                number=number,
                stem=stem,
                options=options,
                correct=tuple(answers.get(number, ())),
                images=imgs,
                blanks=blanks,
            )
        )
    return TopHatQuiz(title=title, subtitle=subtitle, exported=exported, questions=questions)
