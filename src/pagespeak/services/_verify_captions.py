"""Verify checks on a document's picture captions.

Captions are looked up the way the vision pass stores them: by the picture's
perceptual hash in `.vision-cache/`. After vision, a picture's alt text IS its
caption, so doubts are read from the master's alts.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._image_refs import parse_image_refs
from ._verify_doc import VerifyDoc
from ._verify_finding import CheckResult, VerifyFinding, finding_key
from ._verify_output import is_remote, local_target
from ._vision_inject import alt_text_by_basename

_PRE_VISION_SUFFIXES = (
    ".structured.md",
    ".repaired.md",
    ".normalized.md",
    ".cleaned.md",
    ".raw.md",
)
# A caption doubts its given label outright, by likening the picture to something else,
# or by naming that label and disputing it; "The label reads …" alone quotes printed text.
_DOUBT_RE = re.compile(
    r"mislabel|(?:does not|doesn't|do not|don't) match (?:the|its) (?:label|title|caption|description)",
    re.IGNORECASE,
)
_LOOKS_RE = re.compile(
    r"\b(?:image|picture|photo(?:graph)?|figure|diagram|illustration|drawing|this|it)\b[^.;]{0,40}?"
    r"\b(?:looks more like|more closely resembles|actually (?:shows|depicts)|may actually be)\b",
    re.IGNORECASE,
)
_GIVEN_RE = re.compile(
    r"\b(?:the|its|this)\s+(?:source|existing|original|provided|given|supplied)\s+"
    r"(?:description|label|caption|title|alt text)|\bthe alt text|despite the label|"
    r"(?:al)?though labell?ed",
    re.IGNORECASE,
)
_AGREE_RE = re.compile(
    r"(?:\bconsistent with|\bin line with|\bmatching|\bagreeing with|^\W*as)\s+(?:the|its|this)\s+"
    r"(?:source|existing|original|provided|given|supplied)\s+(?:description|label|caption|title|alt text)",
    re.IGNORECASE,
)
_NEUTRAL_RE = re.compile(
    r"\bnot (?:shown|pictured|visible|depicted|labell?ed|(?:drawn )?to scale)\b", re.IGNORECASE
)
_TURN_RE = re.compile(
    r"^\W*(?:(?:it|this)\s+(?:is|was)\s+actually|in fact|actually|however|but)\b", re.IGNORECASE
)
_CODE_RE = re.compile(r"[\d_]")  # one word holding these is a file or camera name: IMG_2034
_CONTRADICT_RE = re.compile(
    r"not match|incorrect|contradict|contrary|inconsistent|wrong|despite|however|\bbut\b|"
    r"rather than|instead of|\bnot\b|n't\b|actually",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WS_RE = re.compile(r"\s+")
_FILE_NAME_RE = re.compile(r"^.+\.(?:png|jpe?g|gif|webp|svg|bmp|tiff?)$", re.IGNORECASE)
# A camera's or an app's own numbering: IMG 2034, DSC_0042, Untitled 3, Screenshot 2024-01-02 at 10.11.12
_CAMERA_NAME_RE = re.compile(
    r"^(?:img|dsc[fn]?|pxl|mvimg|dji|gopr|cimg|vid|scan|untitled|screen ?shot)[\s_-]*"
    r"\d[\d\s_.:-]*(?:(?:at|am|pm)\b[\d\s_.:-]*)*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[^\W\d_][\w'-]*|\S*=\S*")
_FILLER = frozenset(
    {
        *("a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"),
        *("figure", "fig", "image", "images", "picture", "photo", "photograph", "table", "panel"),
        *("view", "page", "screenshot", "screen", "shot", "illustration", "diagram", "graphic"),
        *("icon", "user-added"),
    }
)
_IDENTIFIER_RE = re.compile(
    r"\b(\d+(?:[.\-]\d+)+[a-z]?)\b|"
    r"\b(?:figure|fig\.?|table|panel|plate|exhibit|activity|chart|map|step|question|view)\s+"
    r"(\d+(?:[.\-]\d+)*[a-z]?)\b"
)


def _vision_skip(doc: VerifyDoc) -> str | None:
    if not doc.flags.get("diagrams"):
        return "vision was off for this run"
    if doc.flags.get("preserve_alt"):
        return "faithful mode keeps the source alt text, so no caption is added"
    return None


def _shown_alts(doc: VerifyDoc) -> dict[Path, str]:
    """Each local picture the master shows → the alt text it shows it with (first use)."""
    shown: dict[Path, str] = {}
    for ref in parse_image_refs(doc.master_text):
        path = local_target(doc.master, ref.target)
        if path is not None:
            shown.setdefault(path, ref.alt)
    return shown


def _identifiers(text: str) -> set[str]:
    """Figure/table-style numbers: `4.3`, `6-9`, or a number right after a label word."""
    found: set[str] = set()
    for match in _IDENTIFIER_RE.finditer(text.casefold().replace("–", "-")):
        found.add(match.group(1) or match.group(2))
    return found


def _describes(alt: str) -> bool:
    """Alt text that says what the picture shows. "A photo of a lighthouse." and
    "Apollo 11" do; "Sidebar 19.4 image", "User-added image" and "IMG 2034" are a
    label, filler and a camera's numbering."""
    text = alt.strip()
    if not text or _FILE_NAME_RE.match(text) or is_remote(text) or _CAMERA_NAME_RE.match(text):
        return False
    if " " not in text and _CODE_RE.search(text):
        return False
    words = [w for w in _WORD_RE.findall(text) if w.casefold().rstrip(".") not in _FILLER]
    return len(words) >= 2 or (len(words) == 1 and not _identifiers(text))


def check_captions(doc: VerifyDoc, phashes: dict[Path, str | None]) -> CheckResult:
    """Every picture the master shows has a caption: a vision-cache entry, or
    source alt text that describes it (a publisher's alt is a caption)."""
    if (reason := _vision_skip(doc)) is not None:
        return CheckResult("captions", skipped=reason)
    cache = doc.root / ".vision-cache"
    shown = _shown_alts(doc)
    findings: list[VerifyFinding] = []
    for path, phash in phashes.items():
        key = finding_key("captions", path.name)
        where = (
            path.relative_to(doc.root).as_posix() if path.is_relative_to(doc.root) else str(path)
        )
        alt = shown.get(path, "")
        if phash is None:
            message = "could not read this picture to look up its caption"
            findings.append(VerifyFinding("captions", key, where, message, blocking=False))
        elif not (cache / f"{phash}.json").is_file() and not _describes(alt):
            message = f"picture has no caption: no vision caption, and its alt text ({alt.strip()[:60]!r}) does not describe it"
            findings.append(VerifyFinding("captions", key, where, message))
    return CheckResult("captions", tuple(findings))


def pre_vision_checkpoint(doc: VerifyDoc) -> Path | None:
    """The last checkpoint before vision, where each picture still has its own title."""
    return next((p for s in _PRE_VISION_SUFFIXES if (p := doc.checkpoint(s)) is not None), None)


def _pre_vision_alts(doc: VerifyDoc) -> dict[str, str] | None:
    path = pre_vision_checkpoint(doc)
    if path is None:
        return None
    return alt_text_by_basename(path.read_text(encoding="utf-8", errors="replace"))


def check_shared_captions(doc: VerifyDoc, phashes: dict[Path, str | None]) -> CheckResult:
    """Pictures the master shows under one caption that names the number of
    only some of their titles ("Table 4.3" on the Table 4.4 picture). The cache
    holds one caption per picture hash, and a caption opens with the title its
    picture was given; two descriptions of one photo share it harmlessly."""
    if (reason := _vision_skip(doc)) is not None:
        return CheckResult("shared_captions", skipped=reason)
    alts = _pre_vision_alts(doc)
    if alts is None:
        return CheckResult(
            "shared_captions", skipped="no pre-vision checkpoint holds each picture's own title"
        )
    shown = _shown_alts(doc)
    by_hash: dict[str, list[Path]] = {}
    for path, phash in phashes.items():
        if phash is not None:
            by_hash.setdefault(phash, []).append(path)
    findings: list[VerifyFinding] = []
    for paths in by_hash.values():
        if len({shown.get(p) for p in paths}) > 1:
            continue  # each still shows its own text
        titles: dict[str, str] = {}
        for path in paths:
            alt = _WS_RE.sub(" ", alts.get(path.name, "")).strip()
            if alt and not _FILE_NAME_RE.match(alt):
                titles.setdefault(alt.casefold(), alt)
        if len(titles) < 2:
            continue
        ids = [_identifiers(t) for t in titles.values()]
        distinct = set().union(*ids) - ids[0].intersection(*ids[1:])
        named = distinct & _identifiers(shown.get(paths[0], ""))
        if not named:
            continue
        names = sorted(p.name for p in paths)
        titled = " / ".join(repr(t) for t in sorted(titles.values()))
        findings.append(
            VerifyFinding(
                "shared_captions",
                finding_key("shared_captions", *names),
                ", ".join(names),
                f"identical pictures titled {titled} share one caption naming {', '.join(sorted(named))}",
            )
        )
    return CheckResult("shared_captions", tuple(findings))


def _disputes(sentence: str, after: str) -> bool:
    """`sentence` names the description the picture was given, not to agree with
    it, and disputes it there or as `after` opens."""
    text = _NEUTRAL_RE.sub("", sentence)
    if not _GIVEN_RE.search(text) or _AGREE_RE.search(text.strip()):
        return False
    return bool(_CONTRADICT_RE.search(text) or _TURN_RE.match(after))


def check_doubting_captions(doc: VerifyDoc) -> CheckResult:
    """A caption saying its picture does not match the label it was given: a note,
    since the doubt is read from wording alone."""
    if (reason := _vision_skip(doc)) is not None:
        return CheckResult("doubting_captions", skipped=reason)
    findings: list[VerifyFinding] = []
    seen: set[str] = set()
    for ref in parse_image_refs(doc.master_text):
        name = ref.target.rsplit("/", 1)[-1]
        if name in seen:
            continue
        seen.add(name)
        sentences = _SENTENCE_RE.split(ref.alt)
        for sentence, after in zip(sentences, [*sentences[1:], ""], strict=True):
            doubt = (
                _DOUBT_RE.search(sentence)
                or _LOOKS_RE.search(sentence)
                or _disputes(sentence, after)
            )
            if doubt:
                findings.append(
                    VerifyFinding(
                        "doubting_captions",
                        finding_key("doubting_captions", name),
                        f"{doc.master.name}:{ref.line}",
                        f"{name}: caption doubts its label: {sentence.strip()[:240]}",
                        blocking=False,
                    )
                )
                break
    return CheckResult("doubting_captions", tuple(findings))
