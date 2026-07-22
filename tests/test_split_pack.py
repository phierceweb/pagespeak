"""Tests for services._split_pack — size-targeted section packing.

The packer decides per-branch what becomes a file: a subtree that fits the
size target is ONE file (descendants inlined); an oversized node recurses
into its children; an oversized FLAT node (no sub-headings) is partitioned
at paragraph boundaries into parts that share the node's identity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pagespeak.services._split import split_into_sections

# ~220 bytes per paragraph line; blank-separated => one block each.
_PARA = "Lorem ipsum body content padding out this paragraph to a fixed size xx. " * 3


def _paras(n: int) -> str:
    return "\n\n".join(_PARA for _ in range(n))


def _read(paths: list[Path], name: str) -> str:
    matches = [p for p in paths if p.name == name]
    assert matches, f"{name} not in {[p.name for p in paths]}"
    return matches[0].read_text(encoding="utf-8")


def _names(paths: list[Path]) -> set[str]:
    return {p.name for p in paths}


def test_fitting_subtree_becomes_one_file(tmp_path: Path) -> None:
    """Chapter + subsections under the target -> a single file with the
    subsection headings inlined as content."""
    md = f"# 1. Alpha\n\n{_paras(2)}\n\n## 1.1. Beta\n\n{_paras(2)}\n\n## 1.2. Gamma\n\n{_paras(2)}\n"
    written = split_into_sections(md, tmp_path / "sections", target_kb=4)
    assert _names(written) == {"1-alpha.md"}
    text = _read(written, "1-alpha.md")
    assert "## 1.1. Beta" in text
    assert "## 1.2. Gamma" in text


def test_oversized_chapter_recurses_into_children(tmp_path: Path) -> None:
    """Chapter over the target -> chapter intro file + one file per child."""
    md = (
        f"# 1. Alpha\n\n{_paras(2)}\n\n"
        f"## 1.1. Beta\n\n{_paras(6)}\n\n"
        f"## 1.2. Gamma\n\n{_paras(6)}\n"
    )
    written = split_into_sections(md, tmp_path / "sections", target_kb=2)
    assert _names(written) == {"1-alpha.md", "1-1-beta.md", "1-2-gamma.md"}
    # The parent file keeps only its own intro; children are separate.
    alpha = _read(written, "1-alpha.md")
    assert "## 1.1. Beta" not in alpha.split("---\n\n", 1)[1].replace("- [1.1. Beta]", "")


def test_adaptive_depth_per_branch(tmp_path: Path) -> None:
    """One branch fits (stays whole), the sibling branch is oversized (splits
    deeper) — the decision is per-branch, not per-document."""
    md = (
        f"# 1. Small\n\n{_paras(2)}\n\n## 1.1. Tidy\n\n{_paras(2)}\n\n"
        f"# 2. Big\n\n{_paras(2)}\n\n## 2.1. Huge\n\n{_paras(14)}\n\n## 2.2. Also\n\n{_paras(14)}\n"
    )
    written = split_into_sections(md, tmp_path / "sections", target_kb=2)
    names = _names(written)
    assert "1-small.md" in names  # whole branch, one file
    assert "1-1-tidy.md" not in names
    assert {"2-big.md", "2-1-huge.md", "2-2-also.md"} <= names


def test_flat_monster_partitions_into_parts(tmp_path: Path) -> None:
    """A leaf with no sub-headings but way over target -> paragraph-boundary
    parts sharing the leaf's identity."""
    md = f"# 1. Wall\n\n{_paras(40)}\n"
    written = split_into_sections(md, tmp_path / "sections", target_kb=2)
    names = _names(written)
    assert "1-wall.md" in names
    part_names = {n for n in names if "-part-" in n}
    assert part_names and part_names == names - {"1-wall.md"}
    # Part 2 carries part metadata and joins back to part 1.
    part2 = next(
        t for t in (p.read_text(encoding="utf-8") for p in written) if "part_index: 2" in t
    )
    assert 'parent_id: "1-wall.md"' in part2
    # Part 1 carries the count too.
    part1 = _read(written, "1-wall.md")
    assert "part_index: 1" in part1
    assert f"part_count: {len(names)}" in part1
    # Every part stays under ~target + one block of slack.
    for p in written:
        assert p.stat().st_size < 3 * 1024


def test_partition_never_cuts_inside_fence(tmp_path: Path) -> None:
    """A fenced code block (with internal blank lines) is one unit — no part
    boundary lands inside it."""
    fence = "```\ncode line\n\ncode after blank\n```"
    md = f"# 1. Wall\n\n{_paras(8)}\n\n{fence}\n\n{_paras(8)}\n"
    written = split_into_sections(md, tmp_path / "sections", target_kb=1)
    joined = [p.read_text(encoding="utf-8") for p in written]
    with_fence = [t for t in joined if "```" in t]
    assert len(with_fence) == 1  # the whole fence lives in exactly one part
    assert "code after blank" in with_fence[0]


def test_partition_never_cuts_inside_table(tmp_path: Path) -> None:
    """A pipe table (no internal blank lines) is one block — never split."""
    table = "| a | b |\n|---|---|\n" + "\n".join(f"| r{i} | v{i} |" for i in range(30))
    md = f"# 1. Wall\n\n{_paras(8)}\n\n{table}\n\n{_paras(8)}\n"
    written = split_into_sections(md, tmp_path / "sections", target_kb=1)
    with_table = [t for t in (p.read_text(encoding="utf-8") for p in written) if "| r0 |" in t]
    assert len(with_table) == 1
    assert "| r29 |" in with_table[0]


def test_single_oversized_block_stays_whole(tmp_path: Path) -> None:
    """One giant paragraph larger than the target is never split mid-block."""
    giant = _PARA * 40  # one block, no internal blank lines
    md = f"# 1. Wall\n\n{giant}\n"
    written = split_into_sections(md, tmp_path / "sections", target_kb=1)
    assert _names(written) == {"1-wall.md"}


def test_target_off_by_default(tmp_path: Path) -> None:
    """No target_kb -> every heading still becomes its own file (unchanged)."""
    md = f"# 1. Alpha\n\n{_paras(2)}\n\n## 1.1. Beta\n\n{_paras(2)}\n"
    written = split_into_sections(md, tmp_path / "sections")
    assert _names(written) == {"1-alpha.md", "1-1-beta.md"}


def test_target_kb_rejects_max_level_combo(tmp_path: Path) -> None:
    """target_kb and max_level are competing mechanisms — explicit error."""
    with pytest.raises(ValueError):
        split_into_sections("# 1. A\n\nx\n", tmp_path / "sections", target_kb=8, max_level=2)


def test_packed_output_keeps_identity_order(tmp_path: Path) -> None:
    """order stays 1..N in document order across parent/child/part mixes."""
    md = f"# 1. Small\n\n{_paras(2)}\n\n# 2. Big\n\n{_paras(2)}\n\n## 2.1. Huge\n\n{_paras(14)}\n"
    written = split_into_sections(md, tmp_path / "sections", target_kb=2)
    assert "order: 1" in _read(written, "1-small.md")
    assert "order: 2" in _read(written, "2-big.md")
    assert "order: 3" in _read(written, "2-1-huge.md")
