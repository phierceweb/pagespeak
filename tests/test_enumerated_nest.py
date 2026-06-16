"""Tests for pagespeak.services._enumerated_nest.

Structure-phase pass: a flat run of enumerated-item H1s (panel controls,
wizard steps — `Foo (1)`, `Bar (Step 2)`) are list members the extractor
flattened to H1; they nest one level under their introducing section. Keyed
on the enumerator shape ONLY, so it cannot touch flat-publish articles,
which never carry a trailing `(N)`.
"""

from __future__ import annotations

from pagespeak.services._enumerated_nest import nest_enumerated_item_runs


def test_nests_enumerated_run_under_section() -> None:
    md = (
        "# Front Panel\n\nThe panel has these controls:\n\n"
        "# Power Knob (1)\n\nThe power knob.\n\n"
        "# Volume Knob (2)\n\nThe volume knob.\n\n"
        "# Input Button (3)\n\nThe input button.\n"
    )
    out = nest_enumerated_item_runs(md)
    assert "# Front Panel\n" in out  # section stays H1
    assert "## Power Knob (1)\n" in out  # controls nest to H2
    assert "## Volume Knob (2)\n" in out
    assert "## Input Button (3)\n" in out


def test_step_enumerator_nests() -> None:
    md = (
        "# Data Transfer Wizard\n\nFollow these steps.\n\n"
        "# Choose Source (Step 1)\n\nPick the source.\n\n"
        "# Choose Target (Step 2)\n\nPick the target.\n"
    )
    out = nest_enumerated_item_runs(md)
    assert "# Data Transfer Wizard\n" in out
    assert "## Choose Source (Step 1)\n" in out
    assert "## Choose Target (Step 2)\n" in out


def test_flat_publish_articles_untouched() -> None:
    # Flat-publish: orphan H1s with NO enumerator must stay H1 (siblings).
    md = (
        "# Help\n\nWelcome.\n\n"
        "# What's new\n\nNew stuff.\n\n"
        "# Get started\n\nStart here.\n\n"
        "# Workflow\n\nThe workflow.\n"
    )
    assert nest_enumerated_item_runs(md) == md  # byte-identical


def test_enumerated_item_with_subcontent_nests_subtree() -> None:
    # An enumerated item that owns sub-headings is still a list member, not a
    # section: the item AND its children nest one level (subtree demote).
    md = (
        "# Setup Wizard\n\nintro\n\n"
        "# Choose Source (Step 1)\n\nbody\n\n"
        "## Source Options\n\nopts\n\n"
        "# Run Import (Step 2)\n\ngo\n"
    )
    out = nest_enumerated_item_runs(md)
    assert "# Setup Wizard\n" in out  # section kept at H1
    assert "## Choose Source (Step 1)\n" in out  # item H1 -> H2
    assert "### Source Options\n" in out  # its child H2 -> H3 (subtree demoted)
    assert "## Run Import (Step 2)\n" in out


def test_enumerated_before_any_section_left_alone() -> None:
    # No non-enumerated section precedes -> nothing to nest under -> leave.
    md = "# First (1)\n\nx.\n\n# Second (2)\n\ny.\n"
    assert nest_enumerated_item_runs(md) == md
