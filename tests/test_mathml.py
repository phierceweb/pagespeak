"""Tests for pagespeak.utils._mathml — presentation-MathML → LaTeX pre-pass.

Some HTML sources ship parallel MathML: a presentation tree (`<mrow><msup>…`)
AND a content tree (`<annotation-xml encoding="MathML-Content">`) inside
`<semantics>`. markitdown renders BOTH (doubling) and flattens superscripts
(b²→b2). The pre-pass replaces each `<math>` with `$…$` LaTeX built from the
presentation tree and drops the content tree, so markitdown never sees the
MathML it mangles.
"""

from __future__ import annotations

from pagespeak.utils._mathml import (
    convert_mathml_to_latex,
    prepare_mathml_for_markdown,
    restore_math,
)


def test_superscript_becomes_latex_caret_inline() -> None:
    """y³ in presentation MathML → `$y^{3}$`, and the parallel content-MathML
    (annotation-xml) is dropped so the equation is not doubled."""
    html = (
        '<p><math display="inline"><semantics>'
        "<mrow><msup><mi>y</mi><mn>3</mn></msup></mrow>"
        '<annotation-xml encoding="MathML-Content">'
        "<apply><power/><ci>y</ci><cn>3</cn></apply></annotation-xml>"
        "</semantics></math></p>"
    )
    out = convert_mathml_to_latex(html)
    assert "$y^{3}$" in out
    assert "annotation" not in out  # content tree dropped → no doubling
    assert "<math" not in out  # the whole element is replaced


def test_subscript_becomes_underscore() -> None:
    html = "<math><mrow><msub><mi>x</mi><mn>1</mn></msub></mrow></math>"
    assert "$x_{1}$" in convert_mathml_to_latex(html)


def test_fraction_becomes_frac() -> None:
    html = "<math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>"
    assert r"$\frac{1}{2}$" in convert_mathml_to_latex(html)


def test_sqrt_becomes_sqrt() -> None:
    html = "<math><msqrt><mn>2</mn></msqrt></math>"
    assert r"$\sqrt{2}$" in convert_mathml_to_latex(html)


def test_nth_root_becomes_indexed_sqrt() -> None:
    html = "<math><mroot><mn>8</mn><mn>3</mn></mroot></math>"
    assert r"$\sqrt[3]{8}$" in convert_mathml_to_latex(html)


def test_mtext_becomes_text_command() -> None:
    html = "<math><mrow><mtext>if </mtext><mi>x</mi></mrow></math>"
    assert r"\text{if }" in convert_mathml_to_latex(html)


def test_mspace_becomes_space() -> None:
    html = '<math><mrow><mn>1</mn><mspace width="0.5em"></mspace><mn>2</mn></mrow></math>'
    assert "$1 2$" in convert_mathml_to_latex(html)


def test_unicode_minus_normalized_to_ascii() -> None:
    html = "<math><mrow><mn>2</mn><mo>−</mo><mn>5</mn></mrow></math>"  # U+2212
    assert "$2-5$" in convert_mathml_to_latex(html)


def test_display_block_uses_double_dollar() -> None:
    html = '<math display="block"><mrow><mn>2</mn></mrow></math>'
    assert "$$2$$" in convert_mathml_to_latex(html)


def test_doubled_presentation_plus_content_collapses_to_one() -> None:
    """The real-world failure: presentation + content MathML side by side.
    The output must contain the equation exactly once (no doubling)."""
    html = (
        '<p><math display="inline"><semantics>'
        "<mrow><mn>2</mn><msup><mi>x</mi><mn>2</mn></msup></mrow>"
        '<annotation-xml encoding="MathML-Content">'
        "<apply><times/><cn>2</cn><apply><power/><ci>x</ci><cn>2</cn></apply></apply>"
        "</annotation-xml></semantics></math></p>"
    )
    out = convert_mathml_to_latex(html)
    assert "$2x^{2}$" in out
    assert out.count("x^{2}") == 1


def test_unknown_element_preserves_text() -> None:
    """A not-yet-handled element must never drop its content."""
    html = "<math><mrow><munknown>Z</munknown></mrow></math>"
    assert "Z" in convert_mathml_to_latex(html)


def test_no_math_returns_input_unchanged() -> None:
    html = "<p>plain <b>text</b> with no math</p>"
    assert convert_mathml_to_latex(html) == html


def test_mtext_operator_only_treated_as_operator() -> None:
    """Some sources mark the unary minus as <mtext>−</mtext>; it must become a
    bare `-`, not `\\text{−}`."""
    html = "<math><mrow><mtext>−</mtext><mi>x</mi></mrow></math>"
    assert "$-x$" in convert_mathml_to_latex(html)


def test_prepare_emits_escape_safe_token_then_restores() -> None:
    """The ingest path: <math> → a placeholder token holding NO markdown
    specials (so markitdown can't corrupt the LaTeX), restored afterward."""
    html = "<p><math><mrow><msub><mi>x</mi><mn>1</mn></msub></mrow></math></p>"
    tokenized, mapping = prepare_mathml_for_markdown(html)
    assert "<math" not in tokenized
    assert "$" not in tokenized  # LaTeX lives in the mapping, not the HTML
    assert "_" not in tokenized  # nothing for markitdown to escape
    assert len(mapping) == 1
    assert "$x_{1}$" in restore_math(tokenized, mapping)


def test_restore_is_noop_without_tokens() -> None:
    assert restore_math("plain text", {}) == "plain text"


def test_pretty_printed_mathml_collapses_to_one_line() -> None:
    """Source MathML with newlines/indentation between tags must yield a
    single-line equation — a `$…$` span with newlines inside breaks inline
    math (delimiters mismatch per line). Regression: pretty-printed source
    with newlines between MathML tags."""
    html = (
        "<math><mrow>\n"
        "  <msup><mi>a</mi><mn>2</mn></msup>\n"
        "  <mo>+</mo>\n"
        "  <msup><mi>b</mi><mn>2</mn></msup>\n"
        "</mrow></math>"
    )
    out = convert_mathml_to_latex(html)
    assert "\n" not in out
    assert "$a^{2}+b^{2}$" in out


def test_mover_overbar_becomes_overline() -> None:
    """The repeating-decimal bar: <mover> with a stretchy em-dash over the
    digits → \\overline, not a raw `———` dump. Regression: a repeating
    decimal rendered as `0.714285———`."""
    html = '<math><mover><mrow><mn>714285</mn></mrow><mo stretchy="true">———</mo></mover></math>'
    assert r"$\overline{714285}$" in convert_mathml_to_latex(html)


def test_munder_underbar_becomes_underline() -> None:
    html = "<math><munder><mi>x</mi><mo>_</mo></munder></math>"
    assert r"$\underline{x}$" in convert_mathml_to_latex(html)


def test_mover_nonbar_script_stacks_with_overset() -> None:
    """A non-bar over-script (e.g. the `=?` self-check) stacks faithfully
    rather than being dumped inline."""
    html = "<math><mover><mo>=</mo><mo>?</mo></mover></math>"
    assert r"\overset{?}{=}" in convert_mathml_to_latex(html)


def test_mover_hat_accent() -> None:
    html = "<math><mover><mi>x</mi><mo>^</mo></mover></math>"
    assert r"\hat{x}" in convert_mathml_to_latex(html)


def test_mtable_becomes_latex_matrix() -> None:
    """A MathML table (matrix / system / aligned math) becomes a structured
    LaTeX matrix with & / \\\\ separators, not a jammed run of cells.
    Regression: augmented matrices rendered as `1-3-52-5-4-354`."""
    html = (
        "<math><mtable>"
        "<mtr><mtd><mn>1</mn></mtd><mtd><mn>2</mn></mtd></mtr>"
        "<mtr><mtd><mn>3</mn></mtd><mtd><mn>4</mn></mtd></mtr>"
        "</mtable></math>"
    )
    out = convert_mathml_to_latex(html)
    assert r"\begin{matrix}1 & 2 \\ 3 & 4\end{matrix}" in out


def test_function_names_render_as_operators() -> None:
    """lim/sin/cos/log → \\lim, \\sin … (upright operators), not bare italic
    letters that read as a product of variables. Single identifiers untouched."""
    assert r"\sin" in convert_mathml_to_latex("<math><mi>sin</mi></math>")
    assert r"\lim" in convert_mathml_to_latex("<math><mo>lim</mo></math>")
    assert r"\log" in convert_mathml_to_latex("<math><mi>log</mi></math>")
    # under a limit (munder) the operator is wrapped, not the bare-letter form
    limit = "<math><munder><mo>lim</mo><mrow><mi>h</mi><mo>→</mo><mn>0</mn></mrow></munder></math>"
    out = convert_mathml_to_latex(limit)
    assert r"\underset{h→0}{\lim }" in out
    # a single-letter identifier is NOT an operator
    assert "$s$" in convert_mathml_to_latex("<math><mi>s</mi></math>")


def test_subscript_label_names_not_mapped_to_operators() -> None:
    """min/max collide with subscript labels (r_max, w_max, y_min) and the unit
    'min' (minutes) far more than the rare min/max operators — so they are NOT
    force-mapped. Regression: `r_max`, `ΔG=w_max`, and `(10 min)` were wrongly
    turned into \\max / \\min."""
    assert (
        convert_mathml_to_latex("<math><msub><mi>r</mi><mi>max</mi></msub></math>") == "$r_{max}$"
    )
    assert r"\max" not in convert_mathml_to_latex("<math><mi>max</mi></math>")
    assert r"\min" not in convert_mathml_to_latex("<math><mi>min</mi></math>")


def test_operator_name_in_script_position_is_a_label_not_operator() -> None:
    """Structural guard: even an in-set name (exp, log) is a label — not an
    operator — when it sits in a sub/superscript, so it is not mapped. Robust to
    the whole label class, not just hand-listed exclusions."""
    assert (
        convert_mathml_to_latex("<math><msub><mi>E</mi><mi>exp</mi></msub></math>") == "$E_{exp}$"
    )
    assert (
        convert_mathml_to_latex("<math><msub><mi>t</mi><mi>log</mi></msub></math>") == "$t_{log}$"
    )
    # but as the BASE of a script it IS the operator (sin²-style)
    assert r"\sin" in convert_mathml_to_latex("<math><msup><mi>sin</mi><mn>2</mn></msup></math>")


def test_operator_followed_by_letter_keeps_separator() -> None:
    """A function operator directly followed by a letter must not glue into an
    undefined control sequence. Regression: the change-of-base formula produced
    `\\frac{\\lnM}{\\lnb}` (broken) instead of `\\frac{\\ln M}{\\ln b}`."""
    out = convert_mathml_to_latex("<math><mrow><mi>ln</mi><mi>M</mi></mrow></math>")
    assert r"\lnM" not in out
    assert r"\ln M" in out


def test_brace_delimiter_escaped_not_bare() -> None:
    """A literal brace from <mo> is a set/system delimiter — it must be \\{ / \\}
    (visible, balanced), never a bare { that opens an unclosed LaTeX group.
    Regression: a system of equations rendered as `$${\\begin{matrix}…$$`, and
    set-builder `{x | …}` silently lost its braces."""
    system = convert_mathml_to_latex(
        "<math><mrow><mo>{</mo><mtable><mtr><mtd><mn>1</mn></mtd></mtr></mtable></mrow></math>"
    )
    assert r"\{\begin{matrix}" in system
    setb = convert_mathml_to_latex("<math><mrow><mo>{</mo><mi>x</mi><mo>}</mo></mrow></math>")
    assert r"\{x\}" in setb


def test_hyperbolic_names_not_mapped_to_avoid_corruption() -> None:
    """Some sources mis-encode "cos h" as a single <mi>cosh</mi>; since \\cosh is a
    real LaTeX command (hyperbolic cosine), mapping it would silently corrupt
    "cos h" → hyperbolic. The hyperbolic names are excluded so the token stays
    bare. Regression: the cosine-derivative difference quotient produced \\cosh."""
    assert r"\cosh" not in convert_mathml_to_latex("<math><mi>cosh</mi></math>")
    assert r"\sinh" not in convert_mathml_to_latex("<math><mi>sinh</mi></math>")
    # but genuine separate-atom "cos h" still maps + separates → \cos h
    assert r"\cos h" in convert_mathml_to_latex("<math><mrow><mi>cos</mi><mi>h</mi></mrow></math>")


def test_msubsup_becomes_sub_then_superscript() -> None:
    """<msubsup> — base with BOTH a subscript and a superscript — is the STEM
    workhorse (indexed-and-powered variables, integral limits). It must become
    `base_{sub}^{sup}`. Regression: `x_1^2` flattened to the jammed `x12`."""
    html = "<math><msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup></math>"
    assert "$x_{1}^{2}$" in convert_mathml_to_latex(html)


def test_msubsup_star_superscript() -> None:
    """A starred sample point x_i^* — msubsup with an operator superscript,
    ubiquitous in Riemann-sum notation. Regression: the jammed `xi*`."""
    html = "<math><msubsup><mi>x</mi><mi>i</mi><mo>*</mo></msubsup></math>"
    assert "$x_{i}^{*}$" in convert_mathml_to_latex(html)


def test_munderover_gives_sub_and_superscript_limits() -> None:
    """<munderover> on a big operator (∑ ∫ ∏) carries lower + upper limits;
    the idiomatic, LLM-legible form is sub/superscript: `base_{under}^{over}`.
    Regression: `∑_{i=1}^{n}` flattened to `∑i=1n`."""
    html = (
        "<math><munderover><mo>∑</mo>"
        "<mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>n</mi></munderover></math>"
    )
    assert "$∑_{i=1}^{n}$" in convert_mathml_to_latex(html)


def test_riemann_sum_reads_end_to_end() -> None:
    """The whole STEM failure in one equation: munderover + msubsup together
    must not jam. `∑_{i=1}^{n} f(x_i^*)` — structure fully preserved."""
    html = (
        '<math display="block"><mrow>'
        "<munderover><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>n</mi></munderover>"
        "<mi>f</mi><mo>(</mo><msubsup><mi>x</mi><mi>i</mi><mo>*</mo></msubsup><mo>)</mo>"
        "</mrow></math>"
    )
    assert "$$∑_{i=1}^{n}f(x_{i}^{*})$$" in convert_mathml_to_latex(html)


def test_mfenced_wraps_children_in_its_delimiters() -> None:
    """<mfenced> carries its delimiters in attributes (default parens + comma
    separator); falling through to children silently drops them. Explicit
    open/close/separators are honored."""
    default = "<math><mfenced><mi>x</mi><mi>y</mi></mfenced></math>"
    assert "$(x,y)$" in convert_mathml_to_latex(default)
    brackets = (
        '<math><mfenced open="[" close="]" separators=""><mi>a</mi><mi>b</mi></mfenced></math>'
    )
    assert "$[ab]$" in convert_mathml_to_latex(brackets)
