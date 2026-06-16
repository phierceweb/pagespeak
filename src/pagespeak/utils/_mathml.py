"""Presentation-MathML → LaTeX pre-pass for the HTML ingest path.

Some HTML embeds *parallel* MathML inside ``<semantics>``: a presentation
tree (the visual form) AND a content tree (``<annotation-xml>``). markitdown
renders BOTH — doubling every inline equation — and flattens superscripts and
drops operators. This module rebuilds clean ``$…$`` LaTeX from the
*presentation* tree only.

**Two entry points, because markitdown escapes markdown specials.** Injecting
``$x_{1}$`` straight into the HTML makes markitdown escape the ``_`` (and
``[``), corrupting subscripts and roots. So the ingest path uses
:func:`prepare_mathml_for_markdown` (``<math>`` → an alphanumeric placeholder
token markitdown leaves alone) + :func:`restore_math` (token → ``$latex$``)
*after* markitdown. :func:`convert_mathml_to_latex` does the direct injection
for callers that don't re-run markitdown.

Source-agnostic: it acts on standard W3C presentation MathML. Unknown elements
fall back to their concatenated text — content never vanishes.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag

# Atoms whose text content maps straight to LaTeX (identifiers, numbers).
_TEXT_ATOMS = {"mi", "mn"}
# Transparent grouping wrappers — emit children concatenated.
_GROUPS = {"mrow", "mstyle", "mpadded"}
# Bases that must be brace-wrapped when a script/root binds to them.
_COMPOUND = _GROUPS | {"mfrac", "msqrt", "mroot", "mfenced"}

# Unicode math chars → ASCII so the output isn't littered with codepoints that
# read poorly downstream. Applied to every atom's text; single-char, context-free.
_CHAR_MAP = {
    "−": "-",  # U+2212 MINUS SIGN → hyphen-minus
    # A literal brace in an atom is a set/system *delimiter* (`{x | …}`, the
    # system-of-equations brace), never LaTeX grouping. Escape it so it renders
    # visibly and balanced — a bare `{` opens an unclosed group and breaks the
    # whole equation. Structural braces (from `\frac{}`, `_{}`) are added in
    # f-strings, not via _norm, so they are unaffected.
    "{": "\\{",
    "}": "\\}",
}

# Function / operator names that render upright (\sin x), not as italic letter
# products. MathML ships them as <mi>/<mo> atoms; map each to its LaTeX command.
# Deliberately excluded: `min`/`max`/`deg` (appear far more as subscript labels
# `r_max` and as units than as operators), and the hyperbolic `cosh`/`sinh`/
# `tanh`/`coth` (some sources mis-encode "cos h" as a single `<mi>cosh</mi>`,
# and `\cosh` is a real command — mapping would silently corrupt it). What
# remains never collides with a valid command when mis-glued.
_FUNCTIONS = {
    "lim",
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "arcsin",
    "arccos",
    "arctan",
    "log",
    "ln",
    "exp",
    "det",
}

# A run of bar / dash / line chars over (or under) the base is an overline /
# underline accent — e.g. the repeating-decimal bar `0.\overline{714285}`,
# which some sources ship as a stretchy em-dash. Other over-scripts map to an
# accent command (hat / tilde / vec) or stack with \overset / \underset.
_BAR_CHARS = {"—", "―", "‾", "¯", "-", "_", "̅", "̄", "̲"}
_ACCENTS = {
    "^": "hat",
    "ˆ": "hat",
    "̂": "hat",
    "~": "tilde",
    "˜": "tilde",
    "̃": "tilde",
    "→": "vec",
    "⃗": "vec",
}

# Escape-proof placeholder wrapper (alphanumeric — markitdown won't touch it).
_TOKEN = "xpagespeakmathx"


def _norm(text: str) -> str:
    return "".join(_CHAR_MAP.get(ch, ch) for ch in text)


def convert_mathml_to_latex(html: str) -> str:
    """Replace every ``<math>`` in `html` with inline/display ``$…$`` LaTeX.

    Goes via the placeholder path so the LaTeX is substituted into the *string*
    after serialisation — injecting it as a ``NavigableString`` would let
    BeautifulSoup HTML-escape ``&`` (matrix column separators) to ``&amp;``.
    The markitdown ingest path uses :func:`prepare_mathml_for_markdown` +
    :func:`restore_math` directly (so markitdown never sees the LaTeX).
    """
    tokenized, mapping = prepare_mathml_for_markdown(html)
    return restore_math(tokenized, mapping)


def prepare_mathml_for_markdown(html: str) -> tuple[str, dict[str, str]]:
    """Replace each ``<math>`` with an escape-proof placeholder token; return
    ``(html, {token: "$latex$"})``. Run markitdown on the returned HTML, then
    pass its markdown through :func:`restore_math` with the same mapping."""
    if "<math" not in html:
        return html, {}
    soup = BeautifulSoup(html, "html.parser")
    mapping: dict[str, str] = {}
    for i, (math, latex) in enumerate(_math_replacements(soup)):
        token = f"{_TOKEN}{i}{_TOKEN}"
        mapping[token] = latex
        math.replace_with(NavigableString(token))
    return str(soup), mapping


def restore_math(text: str, mapping: dict[str, str]) -> str:
    """Swap placeholder tokens back to their ``$latex$`` form (post-markitdown)."""
    for token, latex in mapping.items():
        text = text.replace(token, latex)
    return text


def _math_replacements(soup: BeautifulSoup) -> list[tuple[Tag, str]]:
    """For each ``<math>``: its element and the ``$…$`` / ``$$…$$`` LaTeX to
    replace it with (built from the presentation tree, content tree dropped)."""
    out: list[tuple[Tag, str]] = []
    for math in soup.find_all("math"):
        latex = _presentation_latex(math).strip()
        delim = "$$" if math.get("display") == "block" else "$"
        out.append((math, f"{delim}{latex}{delim}"))
    return out


def _presentation_latex(math: Tag) -> str:
    """LaTeX from the presentation subtree of a ``<math>``, skipping the
    ``<semantics>`` content-MathML annotation (the doubling source)."""
    semantics = math.find("semantics")
    root = semantics if semantics is not None else math
    parts: list[str] = []
    for child in root.children:
        if isinstance(child, Tag) and child.name in ("annotation", "annotation-xml"):
            continue
        parts.append(_node_latex(child))
    return "".join(parts)


def _node_latex(node: PageElement) -> str:
    if not isinstance(node, Tag):
        text = str(node)
        # Drop formatting whitespace (newlines / indentation between MathML
        # tags in pretty-printed source) so the equation stays on one line — a
        # `$…$` span with newlines breaks inline math. A bare space may be
        # meaningful between text runs, so keep whitespace that isn't a newline.
        if not text.strip():
            return "" if "\n" in text else text
        return text
    name = node.name
    if name in _TEXT_ATOMS or name == "mo":
        text = _norm(node.get_text())
        if text.strip() in _FUNCTIONS and not _in_script_position(node):
            # Trailing space terminates the control word so it can't glue to a
            # following letter into an undefined command (`\lnM`). Harmless
            # elsewhere — LaTeX collapses it, and outer ends are stripped.
            return f"\\{text.strip()} "
        return text
    if name == "mtext":
        text = node.get_text()
        # Some sources mark the unary minus as <mtext>−</mtext>; treat an
        # operator/punctuation-only mtext as an operator, real words as \text.
        if text.strip() and not any(c.isalpha() for c in text):
            return _norm(text)
        return rf"\text{{{text}}}"
    if name == "mspace":
        return " "
    if name in _GROUPS:
        return _children_latex(node)
    if name in ("msup", "msub"):
        kids = _element_children(node)
        if len(kids) >= 2:
            op = "^" if name == "msup" else "_"
            return f"{_base(kids[0])}{op}{_braced(kids[1])}"
    if name == "mfrac":
        kids = _element_children(node)
        if len(kids) >= 2:
            return rf"\frac{_braced(kids[0])}{_braced(kids[1])}"
    if name == "msqrt":
        return rf"\sqrt{{{_children_latex(node)}}}"
    if name == "mroot":
        kids = _element_children(node)
        if len(kids) >= 2:
            return rf"\sqrt[{_node_latex(kids[1])}]{{{_node_latex(kids[0])}}}"
    if name in ("mover", "munder"):
        kids = _element_children(node)
        if len(kids) >= 2:
            base = _node_latex(kids[0])
            script = _node_latex(kids[1]).strip()
            if script and all(c in _BAR_CHARS for c in script):
                cmd = "overline" if name == "mover" else "underline"
                return rf"\{cmd}{{{base}}}"
            acc = _ACCENTS.get(script) if name == "mover" else None
            if acc:
                return rf"\{acc}{{{base}}}"
            stack = "overset" if name == "mover" else "underset"
            return rf"\{stack}{{{_node_latex(kids[1])}}}{{{base}}}"
    if name == "mtable":
        # Matrices / systems / aligned multi-line math. Without this they
        # collapse to an unreadable run of jammed cells. Render the grid with
        # LaTeX `&` (column) / `\\` (row) separators inside a matrix env.
        rows: list[str] = []
        for tr in _element_children(node):
            if tr.name != "mtr":
                continue
            cells = [_children_latex(td) for td in _element_children(tr) if td.name == "mtd"]
            rows.append(" & ".join(cells))
        if rows:
            return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"
    # Unknown / not-yet-handled element: never drop content.
    return _children_latex(node)


def _children_latex(node: Tag) -> str:
    return "".join(_node_latex(c) for c in node.children)


def _element_children(node: Tag) -> list[Tag]:
    return [c for c in node.children if isinstance(c, Tag)]


def _in_script_position(node: PageElement) -> bool:
    """True when `node` is the script (sub/super/under/over) child of a script
    element — e.g. the `max` in `r_max` or `exp` in `E_exp`. Such a name is a
    label, never a function operator, so it must not be mapped to `\\max`/`\\exp`.
    The base (kids[0]) is NOT a script position — `sin` in `sin²` still maps."""
    parent = node.parent
    if parent is None or parent.name not in (
        "msub",
        "msup",
        "msubsup",
        "munder",
        "mover",
        "munderover",
    ):
        return False
    kids = _element_children(parent)
    return len(kids) >= 2 and node is not kids[0]


def _braced(node: Tag) -> str:
    """Script/fraction argument — always brace-wrapped (`^{3}`)."""
    return f"{{{_node_latex(node)}}}"


def _base(node: Tag) -> str:
    """Script base — brace-wrap only compound bases so the script binds to the
    whole group; a single atom stays bare (`y^{3}`, not `{y}^{3}`)."""
    latex = _node_latex(node)
    if node.name in _COMPOUND:
        return f"{{{latex}}}"
    return latex
