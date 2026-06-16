"""Structure-phase pass: nest enumerated-item runs under their section.

Third sibling to `_flat_source_demote` and `_h1_ratio_rebalance`. Those two
handle *flat-publish* docs, where a run of orphan H1s really are siblings and
should flatten to H2. This pass handles the
*opposite* case those two get wrong: a run of **enumerated list items** that
the extractor flattened to H1 — a panel's controls (`Power Knob (1)`,
`Input Button (2)`), a wizard's steps (`Choose Source (Step 1)`). These are
not divisions; they are members of a list that belongs *under* the section
that introduces it. Each item (and its own sub-headings) is demoted one level
so the whole run nests beneath the preceding (non-enumerated) section.

Why it runs BEFORE `rebalance_orphan_h1s`: nesting the items down drops the
orphan-H1 ratio, so the broad rebalance no longer over-fires and blanket-
demotes the real chapters alongside them.

The discriminator is the **enumerator shape alone** — a trailing `(N)`,
`(N.N)`, or `(Step N)`. Flat-publish articles ("What's new", "Get started")
never carry one, so this pass provably cannot touch them: it fires on exactly
the docs with enumerated-list flattening and nothing else.
"""

from __future__ import annotations

import re

from pf_core.log import get_logger

logger = get_logger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# A bare enumerator at end of heading: (1), (2.1), (Step 3).
_ENUMERATOR_RE = re.compile(r"\(\s*(?:step\s+)?\d+(?:\.\d+)?\s*\)\s*$", re.IGNORECASE)


def _is_enum_h1(level: int, text: str) -> bool:
    return level == 1 and bool(_ENUMERATOR_RE.search(text))


def nest_enumerated_item_runs(text: str) -> str:
    """Demote enumerated-item runs one level so they nest under their section.

    An enumerated item is an H1 whose text ends in `(N)` / `(N.N)` /
    `(Step N)`. Such an item — together with any sub-headings it owns — is a
    list member, not a top-level division: it nests under the section above
    it. A run is the maximal span from an enumerated H1 to (but not including)
    the next NON-enumerated H1 (the next real section); every heading in that
    span is demoted one level (the items go H1→H2, their children H2→H3, …),
    preserving the run's internal shape. Only fires once a non-enumerated
    section H1 has appeared above (there must be a section to nest under);
    H6 headings are left as-is (cannot demote further).

    Args:
        text: post-repair markdown.

    Returns:
        text with enumerated-item runs nested one level, else unchanged.
    """
    lines = text.splitlines(keepends=True)

    heads: list[tuple[int, int, str]] = []  # (line_idx, level, heading_text)
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.rstrip("\n"))
        if m is not None:
            heads.append((i, len(m.group(1)), m.group(2)))

    to_demote: set[int] = set()
    seen_section_h1 = False
    n = len(heads)
    k = 0
    while k < n:
        _, level, htext = heads[k]
        if _is_enum_h1(level, htext):
            if seen_section_h1:
                # Run: this enumerated H1 + its subtree + any following
                # enumerated H1s + subtrees, up to the next non-enumerated H1.
                j = k
                while j < n:
                    lj, lvlj, txtj = heads[j]
                    if lvlj == 1 and not _ENUMERATOR_RE.search(txtj):
                        break  # next real section ends the run
                    to_demote.add(lj)
                    j += 1
                k = j
                continue
            k += 1  # no section above yet — leave it
            continue
        if level == 1:
            seen_section_h1 = True
        k += 1

    demoted = 0
    for li in to_demote:
        m = _HEADING_RE.match(lines[li].rstrip("\n"))
        if m is not None and len(m.group(1)) < 6:  # don't push past H6
            lines[li] = "#" + lines[li]
            demoted += 1

    if demoted:
        logger.info("enumerated_item_nest demoted=%d", demoted)
    return "".join(lines)
