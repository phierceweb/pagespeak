"""Layout backend: the text printed on and around a figure's art, as its label list."""

from __future__ import annotations

import re
from typing import Any

from ._layout_profile import LayoutProfile
from ._layout_text import clean, join

Line = dict[str, Any]


SUBS = dict(zip("0123456789", "₀₁₂₃₄₅₆₇₈₉", strict=True))


def _letter(ln: Line) -> bool:
    return bool(re.fullmatch(r"[a-z][₀-₉]?", ln["text"].strip()))


def join_keys(lines: list[Line]) -> list[Line]:
    """A lettered key: a letter (with its subscript digit) joined to the name set beside it."""
    lines = [dict(ln) for ln in lines]
    for ln in lines:
        # a letter and its subscript read as one line ("l1")
        if re.fullmatch(r"[a-z]\d", ln["text"].strip()):
            ln["text"] = ln["text"].strip()[0] + SUBS[ln["text"].strip()[1]]
    for ln in [ln for ln in lines if re.fullmatch(r"[a-z]", ln["text"].strip())]:
        sub = next(
            (
                s
                for s in lines
                if re.fullmatch(r"\d", s["text"].strip())
                and 0 <= ln["base"] - s["base"] < 3.5
                and -0.5 <= s["x0"] - ln["x1"] < 2.5
            ),
            None,
        )
        if sub is not None:
            ln["text"] = ln["text"].strip() + SUBS[sub["text"].strip()]
            ln["x1"] = sub["x1"]
            lines.remove(sub)
    out = []
    for ln in sorted(lines, key=lambda ln: ln["x0"]):
        if _letter(ln):
            name = next(
                (
                    n
                    for n in lines
                    if n is not ln
                    and not _letter(n)
                    and abs(n["base"] - ln["base"]) < 3.5
                    and 1 <= n["x0"] - ln["x1"] < 20
                    and not n.get("keyed")
                ),
                None,
            )
            if name is not None:
                name["text"] = ln["text"].strip() + " " + name["text"].strip()
                name["x0"] = ln["x0"]
                name["keyed"] = True
                continue
        out.append(ln)
    return out


def _join_wrapped(lines: list[Line]) -> list[Line]:
    """Labels set on two lines, and a key entry's second line set in under its name, joined."""
    entry = re.compile(r"^\d{1,2}\.\s")
    horiz: list[Line] = []
    for ln in sorted(
        (ln for ln in lines if not ln.get("vertical")), key=lambda ln: (-ln["base"], ln["x0"])
    ):

        def step(b: Line, ln: Line = ln) -> bool:
            return bool(
                0 < b["base"] - ln["base"] < 1.7 * max(ln["y1"] - ln["y0"], 5)
                and b["font"] == ln["font"]
            )

        def aligned(b: Line, ln: Line = ln) -> bool:  # flush or centred
            return bool(
                abs(b["x0"] - ln["x0"]) < 3 or abs(b["x0"] + b["x1"] - ln["x0"] - ln["x1"]) < 6
            )

        host = next(
            (
                b
                for b in reversed(horiz)
                if aligned(b)
                and step(b)
                and not entry.match(ln["text"])
                and not b["text"].rstrip().endswith(".")
                and not b.get("keyed")
                and not ln.get("keyed")
            ),
            None,
        )
        if host is None and not entry.match(ln["text"]):
            host = next(
                (
                    b
                    for b in reversed(horiz)
                    if entry.match(b["text"]) and b["x0"] + 4 < ln["x0"] < b["x0"] + 30 and step(b)
                ),
                None,
            )
        if host is not None:
            host["text"] = join(
                host["text"].rstrip(), ln["text"].strip(), host.get("soft_hyphen", False)
            )
            host["base"], host["soft_hyphen"] = ln["base"], ln.get("soft_hyphen", False)
            continue
        horiz.append(dict(ln))
    return horiz


def label_text(lines: list[Line], prof: LayoutProfile) -> list[str]:
    """A figure's printed text: labels in reading order, then numbered labels and key entries in number order."""
    lines = join_keys([ln for ln in lines if ln["text"].strip()])
    # marks on the art; the credit
    lines = [
        ln
        for ln in lines
        if not re.fullmatch(r"([a-z][₀-₉\d]?|\*+|•)( ([a-z][₀-₉\d]?|\*+|•))*", ln["text"].strip())
        and not prof.label_credit.search(ln["text"])
        and ln["text"].strip() not in prof.label_credit_exact
    ]
    for n in [
        ln
        for ln in lines
        if re.fullmatch(r"\d{1,2}\.", ln["text"].strip()) and not ln.get("vertical")
    ]:
        name = min(
            (
                ln
                for ln in lines
                if ln is not n
                and not ln.get("vertical")
                and abs(ln["base"] - n["base"]) < 1.5
                and 0 < ln["x0"] - n["x1"] < 15
                and not re.match(r"\d", ln["text"].strip())
            ),
            key=lambda ln: ln["x0"],
            default=None,
        )
        if name is not None:  # a key number set apart from its name
            name["text"], name["x0"] = n["text"].strip() + " " + name["text"].strip(), n["x0"]
            lines.remove(n)
    horiz = _join_wrapped(lines)
    horiz.sort(key=lambda ln: (-round(ln["y1"] / 3), ln["x0"]))
    vert = sorted((ln for ln in lines if ln.get("vertical")), key=lambda ln: ln["x0"])
    out: list[str] = []
    for ln in horiz + vert:
        t = clean(ln["text"], prof.checkbox)
        if t and not prof.credit.match(t):
            out += t.split(" ") if re.fullmatch(r"\d{1,3}( \d{1,3})+", t) else [t]
    nums = [t for t in out if re.fullmatch(r"\d{1,3}\.?", t)]
    keyed = [t for t in out if re.match(r"^\d{1,3}\.\s", t)]
    rest = [t for t in out if t not in nums and t not in keyed]

    def num_key(t: str) -> int:
        m = re.match(r"\d+", t)
        return int(m.group()) if m else 0

    return rest + sorted(nums, key=num_key) + sorted(keyed, key=num_key)
