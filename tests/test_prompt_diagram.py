from __future__ import annotations

from pagespeak.prompts._diagram import DIAGRAM_PROMPT, DIAGRAM_PROMPT_VERSION


def test_diagram_prompt_loads_at_import_time() -> None:
    assert isinstance(DIAGRAM_PROMPT, str)
    assert len(DIAGRAM_PROMPT) > 100


def test_diagram_prompt_version_is_four() -> None:
    """v2 = alt-text-aware; v3 = preserve a full data-transcription alt;
    v4 = brand-hallucination examples generalized (no named brands)."""
    assert DIAGRAM_PROMPT_VERSION == 4


def test_diagram_prompt_includes_caption_depth_guidance() -> None:
    """The prompt must instruct on caption depth for data charts
    specifically — naming axes, labels, and legends — so charts get more
    than a one-sentence description."""
    assert "Data chart" in DIAGRAM_PROMPT
    assert "axes" in DIAGRAM_PROMPT
    assert "labels" in DIAGRAM_PROMPT or "legend" in DIAGRAM_PROMPT.lower()


def test_diagram_prompt_includes_mermaid_guidance() -> None:
    """Mermaid block must still be requested for diagram-shaped images."""
    assert "Mermaid" in DIAGRAM_PROMPT or "mermaid" in DIAGRAM_PROMPT


def test_diagram_prompt_returns_json_schema() -> None:
    assert "is_diagram" in DIAGRAM_PROMPT
    assert "caption" in DIAGRAM_PROMPT


def test_diagram_prompt_includes_anti_examples_for_anatomical_illustrations() -> None:
    """Anatomical illustrations must be explicitly called out as
    caption-only — both Haiku and Gemini otherwise force Mermaid onto
    cross-sections."""
    text = DIAGRAM_PROMPT.lower()
    # Anti-example category names
    assert "anatomical" in text
    assert "cross-section" in text or "cross section" in text
    # The conceptual rule
    assert "morphological" in text or "spatial" in text


def test_diagram_prompt_scopes_architecture_beta_to_systems() -> None:
    """`architecture-beta` must be restricted to actual system
    architecture diagrams (services, queues, infrastructure), not anatomy
    or biology — the model otherwise reaches for it on anatomical
    illustrations."""
    text = DIAGRAM_PROMPT
    assert "architecture-beta" in text
    # The qualifier
    assert "system architecture" in text.lower()


def test_diagram_prompt_includes_per_type_positive_examples() -> None:
    """Each Mermaid type must give concrete example sources so the LLM
    knows what visual content maps to which diagram."""
    text = DIAGRAM_PROMPT.lower()
    # Each major Mermaid type should appear with example context
    for mermaid_type in ("flowchart", "sequencediagram", "classdiagram", "statediagram"):
        assert mermaid_type in text, f"missing {mermaid_type} reference"


def test_diagram_prompt_anti_examples_time_series_traces() -> None:
    """Time-series / oscilloscope plots are caption-only — a continuous-time
    X-axis must not be forced into `stateDiagram-v2` even when its regions
    are labeled."""
    text = DIAGRAM_PROMPT.lower()
    assert "time-series" in text or "oscilloscope" in text
    assert "continuous time" in text or "continuous-time" in text
    # The negative direction
    assert "not produce" in text


def test_diagram_prompt_anti_examples_chemical_reactions() -> None:
    """Chemical reactions and equilibria are caption-only; the rule must
    name reaction equations and equilibrium arrows explicitly, not just
    structural formulas."""
    text = DIAGRAM_PROMPT.lower()
    assert "equilibri" in text  # 'equilibrium' or 'equilibria'
    assert "reaction" in text


def test_diagram_prompt_audio_signal_flow_is_explicit_flowchart_example() -> None:
    """Audio / electrical signal-flow diagrams must remain firmly in the
    `flowchart` positive examples so hardware signal chains continue to
    render as Mermaid — the time-series anti-examples could otherwise
    over-constrain this category."""
    text = DIAGRAM_PROMPT.lower()
    assert "signal flow" in text or "signal-flow" in text
    assert "audio" in text or "preamp" in text


def test_diagram_prompt_forbids_inventing_brand_names() -> None:
    """A caption must not name a manufacturer/brand/product unless it is
    literally legible in the image; otherwise describe generically. The
    'looks-like is not reads-as' guard blocks wrong-vendor substitutions."""
    text = DIAGRAM_PROMPT
    lower = text.lower()
    # The rule is present and framed as a hard prohibition on invention.
    assert "invent a brand" in lower or "never invent a brand" in lower
    assert "legible" in lower
    # The generic-fallback instruction.
    assert "generic" in lower
    # The looks-like guard (the specific failure mode).
    assert "looks like" in lower or "looks-like" in lower


def test_diagram_prompt_forbids_inventing_product_category() -> None:
    """The don't-invent rule must extend to product CATEGORY, not just
    brand. Ambiguous schematic line-art must be described by geometry +
    visible labels, never asserted to be a specific device type without
    support."""
    text = DIAGRAM_PROMPT
    lower = text.lower()
    # The rule now names category, not just brand/product name.
    assert "category" in lower
    # The geometry-only fallback for ambiguous line-art.
    assert "geometry" in lower
    # The both-axes framing in the closing line.
    assert "what-it-is" in lower or "what it is" in lower


def test_diagram_prompt_small_glyph_caption_tier_is_terse() -> None:
    """Small decorative glyphs (logo / icon / knob / status dot) get their
    own caption tier capped at one short clause, and the prompt explicitly
    forbids 'commonly used to represent' / 'typically' purpose-speculation."""
    text = DIAGRAM_PROMPT
    lower = text.lower()
    # The glyph tier is named and distinct from photo/screenshot.
    assert "icon" in lower
    assert "clause" in lower
    # The anti-speculation instruction.
    assert "commonly represents" in lower or "commonly used to represent" in lower
    assert "typically" in lower


def test_diagram_prompt_icon_and_lone_lineart_guards() -> None:
    """Two reinforcements against confident-but-wrong identities: (1) an
    unidentifiable small glyph is named by role/shape, not guessed as a
    real-world object; (2) a lone dimension/orthographic line-drawing with
    no legible text is geometry-only, never a vehicle / animal / weapon /
    medical instrument."""
    text = DIAGRAM_PROMPT
    lower = text.lower()
    # (1) icon-class guard: the paintbrush → syringe/wrench failure is named,
    # with the name-by-role fallback.
    assert "syringe" in lower
    assert "toolbar button" in lower or "control icon" in lower
    # (2) lone line-art guard: geometry-only, with the concrete failure nouns.
    assert "lone orthographic or dimension line-drawing" in lower
    assert "wheeled vehicle" in lower
    assert "endoscope" in lower


def test_diagram_prompt_callout_transcription_rule() -> None:
    """Caption-only images with numbered/lettered/arrow callouts must be
    enumerated one entry per label (never collapsed to 'labeled A–H'), and
    a bare glyph described by visual FORM, never the tool/command it
    invokes — the positive complement of the don't-invent rule."""
    text = DIAGRAM_PROMPT
    lower = text.lower()
    # The rule is present and names the callout concept.
    assert "callout" in lower
    # Enumerate-don't-collapse: one entry per label, never flatten the set.
    assert "one entry per label" in lower
    assert "never collapse" in lower
    # The glyph guard: describe visual form, not the tool/command it invokes.
    assert "visual form" in lower
    # Framed as the positive complement of the don't-invent rule.
    assert "positive complement" in lower


# --- alt-text-aware rendering (v2) ------------------------------------------


def test_render_diagram_prompt_injects_original_alt() -> None:
    """The figure's existing alt text is substituted into the prompt so the
    model can correct / keep / enrich it."""
    from pagespeak.prompts._diagram import render_diagram_prompt

    out = render_diagram_prompt("Unmistakable BP cuff source alt ZZZQ")
    assert "Unmistakable BP cuff source alt ZZZQ" in out


def test_render_diagram_prompt_none_uses_placeholder() -> None:
    """No original alt → a literal `(none provided)` marker (so the
    write-from-scratch branch fires), never a leaked `@@ORIGINAL_ALT@@`."""
    from pagespeak.prompts._diagram import render_diagram_prompt

    out = render_diagram_prompt(None)
    assert "(none provided)" in out
    assert "@@ORIGINAL_ALT@@" not in out


def test_render_diagram_prompt_blank_uses_placeholder() -> None:
    """Whitespace-only alt is treated as no description."""
    from pagespeak.prompts._diagram import render_diagram_prompt

    out = render_diagram_prompt("   ")
    assert "(none provided)" in out


def test_diagram_prompt_has_no_unrendered_token() -> None:
    """The module-level constant must be fully rendered (token substituted)."""
    assert "@@ORIGINAL_ALT@@" not in DIAGRAM_PROMPT


def test_diagram_prompt_includes_existing_description_contract() -> None:
    """The alt-aware contract: treat the source description as a starting
    reference, correct/keep/enrich it, and follow the image on conflict."""
    lower = DIAGRAM_PROMPT.lower()
    assert "existing description" in lower
    assert "starting reference" in lower
    assert "follow the image" in lower


def test_diagram_prompt_preserves_data_transcription_alt() -> None:
    """v3: when the source alt is a full transcription of tabular/enumerated
    data (a rasterized table's rows), keep it — do NOT collapse it into a
    structural summary, which makes the per-row data unsearchable."""
    lower = DIAGRAM_PROMPT.lower()
    assert "transcription" in lower
    assert "unsearchable" in lower
    # the rule names the table-image case and the don't-summarize direction
    assert "table" in lower
    assert "structural summary" in lower
