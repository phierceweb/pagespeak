"""Verify check `split_conservation`: the section files hold the master exactly once.

The splitter adds frontmatter, a `> ↑` breadcrumb and a `## Subsections` list
to each file, rewrites image paths and in-document links, and drops
heading-only shells and the table of contents. Everything else in the master
lands in exactly one section file: a line in none is missing from the section
index, a line in two is duplicated there, and a line only the sections hold
means they were written from a different master.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ._fences import fence_flags
from ._heading_sanity import is_toc_phantom_heading
from ._image_refs import replace_image_refs
from ._verify_doc import VerifyDoc, split_frontmatter
from ._verify_finding import CheckResult, VerifyFinding, finding_key

_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$")
_TOC_HEADING_RE = re.compile(r"^#+\s*Table of Contents\s*$", re.IGNORECASE)
_SUBSECTIONS = "## Subsections"
_CRUMB = "> ↑"
_PAGE_ANCHOR_RE = re.compile(r'<span id="page-\d+-\d+"></span>')
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\([^)]*\)")
# A link wrapped onto two lines leaves its `](target)` tail at the start of the second.
_LINK_TAIL_RE = re.compile(r"^([^\[]*?)\]\([^)]*\)")
_TAG_RE = re.compile(r'pagespeak-image="[^"]*?([^"/]+)"')
_PART_RE = re.compile(r"\s*\(part \d+ of \d+\)$", re.IGNORECASE)
# The splitter rewrites a numbered heading's number (`Chapter 1 Cells` → `1. Cells`).
_NUMBERING_RE = re.compile(
    r"^(?:(?:chapter|part|section|unit|module|lesson|activity)\s+)?\d+(?:[.\-]\d+)*[.:]?\s+",
    re.IGNORECASE,
)
_BARE_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\s")
_CRUMB_UNSAFE_RE = re.compile(r"[|\[\]()<>\\]+")
_EMPHASIS_RE = re.compile(r"[*_]+")
_WS_RE = re.compile(r"\s+")
_MAX_FILES_NAMED = 3


def _normalize(line: str) -> str:
    """A line as both copies can agree on: image refs by file name, links by label."""
    line = _PAGE_ANCHOR_RE.sub("", line)
    line, _ = replace_image_refs(line, lambda r: f"![{r.alt}]({r.target.rsplit('/', 1)[-1]})")
    line = _LINK_TAIL_RE.sub(r"\1]", _LINK_RE.sub(r"[\1]", line))
    line = _TAG_RE.sub(r'pagespeak-image="\1"', line)
    # Emphasis markers differ between writers of the same text; they carry none.
    return _WS_RE.sub(" ", _EMPHASIS_RE.sub("", line)).strip()


def _heading_text(raw: str) -> str:
    return _WS_RE.sub(" ", _LINK_RE.sub(r"\1", _normalize(raw))).strip().rstrip("#").strip()


def _contents_entry(title: str) -> bool:
    """The splitter's own test, on the `N. Title` form it gives numbered headings."""
    return is_toc_phantom_heading(title) or is_toc_phantom_heading(
        _BARE_NUMBER_RE.sub(r"\1. ", title)
    )


def title_key(text: str) -> str:
    """A heading's title as the master, a section file and a breadcrumb all spell it."""
    plain = _WS_RE.sub(" ", _CRUMB_UNSAFE_RE.sub(" ", _PART_RE.sub("", text))).strip()
    return _NUMBERING_RE.sub("", plain).casefold()


@dataclass
class _Heading:
    title: str
    line: int
    level: int
    has_body: bool = False


@dataclass
class _Parsed:
    body: Counter[str] = field(default_factory=Counter)
    first_line: dict[str, int] = field(default_factory=dict)
    headings: list[_Heading] = field(default_factory=list)
    crumbs: set[str] = field(default_factory=set)
    cut: set[str] = field(default_factory=set)  # breadcrumbs the splitter cut short (…)
    # Lines under a heading shaped like a contents entry, which the splitter drops.
    contents_lines: set[str] = field(default_factory=set)


def _carried(key: str, have: set[str], sections: _Parsed) -> bool:
    """A section file carries the title: as a heading, as a breadcrumb, or as one
    the splitter cut short."""
    return key in have or key in sections.crumbs or any(key.startswith(c) for c in sections.cut)


def _front_end(master: _Parsed, sections: _Parsed) -> int:
    """Master line where what the sections must hold starts: the first heading,
    or past a lone H1 title and the lines under it when no section carries that
    title as a heading or breadcrumb (a quiz splitter keeps the title block out)."""
    heads = master.headings
    levels = [h.level for h in heads]
    if levels and levels.count(1) == 1 and levels[0] == 1 and len(heads) > 1:
        have = {title_key(h.title) for h in sections.headings}
        if not _carried(title_key(heads[0].title), have, sections):
            return heads[1].line
    return heads[0].line if heads else 0


def _generated_tail(lines: list[str], fenced: list[bool]) -> int:
    """Where a section file's `## Subsections` list starts: always the last
    block, and child titles may carry brackets no link pattern parses."""
    for i in range(len(lines) - 1, -1, -1):
        if not fenced[i] and lines[i].strip() == _SUBSECTIONS:
            rest = [line for line in lines[i + 1 :] if line.strip()]
            return i if all(line.lstrip().startswith("- ") for line in rest) else len(lines)
    return len(lines)


def _parse(text: str, *, section: bool) -> _Parsed:
    out = _Parsed()
    body, offset = split_frontmatter(text)
    lines = body.splitlines()
    fenced = fence_flags(lines)
    end = _generated_tail(lines, fenced) if section else len(lines)
    in_toc = in_entry = False
    for i in range(end):
        stripped = lines[i].strip()
        if section and not fenced[i] and stripped.startswith(_CRUMB):
            parts = [p.rstrip() for p in _LINK_RE.sub(r"\1", stripped[len(_CRUMB) :]).split(" / ")]
            out.crumbs |= {title_key(p) for p in parts if not p.endswith("…")}
            out.cut |= {key for p in parts if p.endswith("…") and (key := title_key(p.rstrip("…")))}
            continue
        match = None if fenced[i] else _HEADING_RE.match(stripped)
        if match:
            in_toc = bool(_TOC_HEADING_RE.match(stripped))
            title = _heading_text(match.group(2))
            in_entry = _contents_entry(title)
            if not in_toc:
                out.headings.append(_Heading(title, offset + i + 1, len(match.group(1))))
            continue
        if in_toc and (not stripped or stripped[0] in "-*+["):
            continue
        in_toc = False
        norm = _normalize(lines[i])
        if not norm:
            continue
        out.body[norm] += 1
        out.first_line.setdefault(norm, offset + i + 1)
        if in_entry:
            out.contents_lines.add(norm)
        if out.headings:
            out.headings[-1].has_body = True
    return out


def _finding(kind: str, text: str, where: str, message: str, blocking: bool) -> VerifyFinding:
    key = finding_key("split_conservation", kind, text)
    return VerifyFinding("split_conservation", key, where, message, blocking)


def _heading_findings(
    master: _Parsed, sections: _Parsed, name: str, *, strict: bool
) -> list[VerifyFinding]:
    have = {title_key(h.title) for h in sections.headings}
    front_end = _front_end(master, sections)
    findings: list[VerifyFinding] = []
    for h in master.headings:
        if not h.has_body or _carried(title_key(h.title), have, sections):
            continue
        blocking = strict and h.line >= front_end and not _contents_entry(h.title)
        message = f"heading with a body is in no section file: {h.title}"
        findings.append(_finding("heading", h.title, f"{name}:{h.line}", message, blocking))
    return findings


def _line_findings(
    master: _Parsed, sections: _Parsed, files_of: dict[str, list[str]], name: str, *, strict: bool
) -> list[VerifyFinding]:
    """A line in no section file, or in the sections but not the master, fails;
    so does a line the master holds once and the sections twice. A boilerplate
    line whose copy count merely differs is a note."""
    front_end = _front_end(master, sections)
    findings: list[VerifyFinding] = []
    for norm in master.body.keys() | sections.body.keys():
        have, want = sections.body[norm], master.body[norm]
        if have == want:
            continue
        if want and not have:
            line = master.first_line[norm]
            blocking = strict and line >= front_end and norm not in master.contents_lines
            message = f"in the master but in no section file: {norm[:200]}"
            findings.append(_finding("lost", norm, f"{name}:{line}", message, blocking))
            continue
        files = ", ".join(files_of.get(norm, [])[:_MAX_FILES_NAMED]) or name
        message = f"{have} time(s) in the section files, {want} in the master: {norm[:200]}"
        kind = "repeated" if have > want else "fewer"
        findings.append(_finding(kind, norm, files, message, want <= 1 and have > want))
    return findings


def check_split(doc: VerifyDoc) -> CheckResult:
    """Lines of the master in no section file, lines the sections hold that the
    master does not (or twice where the master has one), and headings with a
    body that no section file carries."""
    if not (doc.root / "sections").is_dir():
        return CheckResult("split_conservation", skipped="no sections/ folder")
    master = _parse(doc.master_text, section=False)
    sections = _Parsed()
    files_of: dict[str, list[str]] = {}
    for path in doc.section_files:
        parsed = _parse(path.read_text(encoding="utf-8", errors="replace"), section=True)
        sections.body.update(parsed.body)
        sections.headings += parsed.headings
        sections.crumbs |= parsed.crumbs
        sections.cut |= parsed.cut
        for norm in parsed.body:
            files_of.setdefault(norm, []).append(path.relative_to(doc.root).as_posix())
    # English-only drops non-English branches from the sections on purpose.
    strict = not doc.flags.get("english_only")
    name = doc.master.name
    findings = _heading_findings(master, sections, name, strict=strict)
    findings += _line_findings(master, sections, files_of, name, strict=strict)
    findings.sort(key=lambda f: (not f.blocking, f.key))
    return CheckResult("split_conservation", tuple(findings))
