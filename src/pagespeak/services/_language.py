"""Conservative section-language classification for the opt-in `--english-only`
split filter.

`section_is_non_english(text)` returns True ONLY when the text is clearly not
English — safe to drop. Anything short or ambiguous returns False (kept), so a
specs table, a one-line English note, or English prose with a few Greek math
symbols (α, ΔE) is never lost. Two signals:

  1. >30% non-Latin letters → CJK / Cyrillic / Greek-language / Arabic / Thai.
  2. a long-enough Latin-script run with near-zero English function words AND a
     real density of distinctively-foreign ones → a Latin-script translation
     (German / French / Italian / Spanish / …). The foreign-evidence half is
     essential: an English specs table (model numbers, MHz/dB units) is
     stopword-poor too, so sparse-English alone would wrongly flag it — the
     foreign-word requirement keeps it.

This is a content heuristic, so it lives behind the opt-in flag and is NEVER on
by default — the project charter is that a messy source yields faithful output,
not output silently edited to a guess. Explicitly asking for English-only is the
exception that proves the rule.
"""

from __future__ import annotations

import re

# High-signal English function words: common in English, rare in the Latin-script
# languages a multilingual manual repeats itself in. The aggregate ratio
# separates English (typically 15-40%) from a translation (~0-4%).
_ENGLISH_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "of",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "with",
        "for",
        "you",
        "your",
        "which",
        "what",
        "have",
        "has",
        "had",
        "will",
        "would",
        "should",
        "could",
        "not",
        "they",
        "their",
        "our",
        "we",
        "from",
        "there",
        "where",
        "when",
        "who",
        "about",
        "than",
        "then",
        "such",
        "other",
        "also",
        "each",
        "may",
        "must",
        "shall",
        "can",
        "its",
        "it",
        "as",
        "at",
    }
)

# Distinctively-foreign high-frequency function words from the Latin-script
# languages a multilingual manual repeats itself in (German / Spanish / Italian /
# French / Portuguese / Dutch). Deliberately EXCLUDES tokens that collide with
# common English words (per, con, die, den, van, door, met, plus, son, …) so an
# English spec table never accumulates a false foreign score. A translation's
# PROSE is dense with these; an English specs table ("Pin assignment", model
# numbers, MHz/dB units) has none — that's the discriminator that stopword
# density alone misses.
_FOREIGN_FUNCTION_WORDS = frozenset(
    {
        # German
        "der",
        "das",
        "und",
        "für",
        "von",
        "sind",
        "ein",
        "eine",
        "nicht",
        "auf",
        "dem",
        "zur",
        "zum",
        "durch",
        "oder",
        "auch",
        "werden",
        "wird",
        "sich",
        "aus",
        "bei",
        "einer",
        "einem",
        "eines",
        "beim",
        "vom",
        "mit",
        # Spanish
        "el",
        "los",
        "las",
        "del",
        "una",
        "por",
        "para",
        "pero",
        "más",
        "está",
        "como",
        "esta",
        "este",
        "esto",
        "sus",
        "muy",
        "donde",
        "cuando",
        "uno",
        # Italian
        "il",
        "lo",
        "gli",
        "di",
        "della",
        "dei",
        "delle",
        "non",
        "sono",
        "che",
        "alla",
        "alle",
        "nella",
        "nel",
        "dello",
        "degli",
        "questa",
        "questo",
        # French
        "les",
        "des",
        "et",
        "une",
        "pour",
        "avec",
        "est",
        "sont",
        "qui",
        "aux",
        "cette",
        "dans",
        "vous",
        "nous",
        "être",
        "leur",
        "ces",
        # Portuguese
        "os",
        "da",
        "em",
        "um",
        "uma",
        "não",
        "são",
        "dos",
        "ao",
        "pela",
        "pelo",
        "também",
        # Dutch
        "het",
        "een",
        "voor",
        "zijn",
        "niet",
        "aan",
        "ook",
        "wordt",
        "deze",
    }
)

# Unicode letters only (any script), no digits/underscore — keeps `für`,
# `résidant` whole rather than splitting on the accent.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Image refs carry pagespeak's vision captions, which are ALWAYS English — they
# must not bias a foreign section toward "English". Stripped before judging so
# the verdict reflects the section's own source prose.
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

_KEEP_BELOW_ALPHA = 12  # below this many letters → too little to classify at all → keep
_MIN_ALPHA = 30  # below this many Latin letters → could be a short English heading → keep
_MIN_WORDS = 20  # fewer words than this → too little for the stopword test → keep
_NON_LATIN_FRACTION = 0.30
_ENGLISH_STOPWORD_FLOOR = 0.06
_FOREIGN_FUNCTION_FLOOR = 0.06  # min density of foreign function words to call it a translation


def _is_non_latin_letter(c: str) -> bool:
    o = ord(c)
    return (
        0x0370 <= o <= 0x03FF  # Greek
        or 0x0400 <= o <= 0x052F  # Cyrillic (+ supplement)
        or 0x0590 <= o <= 0x05FF  # Hebrew
        or 0x0600 <= o <= 0x06FF  # Arabic
        or 0x0E00 <= o <= 0x0E7F  # Thai
        or 0x3040 <= o <= 0x30FF  # Hiragana / Katakana
        or 0x3400 <= o <= 0x9FFF  # CJK
        or 0xAC00 <= o <= 0xD7AF  # Hangul
        or 0xF900 <= o <= 0xFAFF  # CJK compatibility
    )


def section_is_non_english(text: str) -> bool:
    """True only when `text` is CLEARLY not English (safe to drop). Conservative:
    short or ambiguous text returns False (kept)."""
    text = _IMAGE_RE.sub(" ", text)  # English vision captions aren't source language
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) < _KEEP_BELOW_ALPHA:
        return False
    # Non-Latin script (CJK / Cyrillic / Greek-language) is unambiguous — there's
    # no risk of catching English — so drop even a short section.
    if sum(_is_non_latin_letter(c) for c in alpha) / len(alpha) > _NON_LATIN_FRACTION:
        return True
    if len(alpha) < _MIN_ALPHA:
        return False  # short Latin-script — could be a short English heading → keep
    words = _WORD_RE.findall(text.lower())
    if len(words) < _MIN_WORDS:
        return False
    stop = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    if stop / len(words) >= _ENGLISH_STOPWORD_FLOOR:
        return False  # enough English function words → English prose → keep
    # Sparse English alone is NOT proof of a foreign language — an English
    # specs table (model numbers, MHz/dB units, "Pin assignment") is just as
    # stopword-poor and must be kept. Require POSITIVE foreign evidence: a real
    # density of distinctively-foreign function words, which a translation's
    # prose carries and a specs table does not.
    foreign = sum(1 for w in words if w in _FOREIGN_FUNCTION_WORDS)
    return foreign / len(words) >= _FOREIGN_FUNCTION_FLOOR
