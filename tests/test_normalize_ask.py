"""Tests for services._normalize_ask — one heading-normalize question: its cache,
its mode's prompt, and the call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pagespeak.prompts._heading_normalize import HEADING_NORMALIZE_PROMPT_VERSION
from pagespeak.prompts._heading_normalize_dehead import HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION
from pagespeak.prompts._heading_normalize_full import HEADING_NORMALIZE_FULL_PROMPT_VERSION
from pagespeak.services._heading_normalize import _extract_headings
from pagespeak.services._normalize_ask import _Asker, _mode_request, _read_cached_response
from pagespeak.services._normalize_llm import _cache_key

_MD = "# Guide\n\nAbout it.\n\n## Setup\n\nSet it up.\n"


def _asker(tmp_path: Path | None, invoke=lambda _p: "1: 1\n2: 2") -> _Asker:
    return _Asker(_MD, "llm_full", invoke, tmp_path, "some-model", None)


def test_cache_files_are_named_by_key_and_chunk_start(tmp_path: Path) -> None:
    headings = _extract_headings(_MD)
    key = _cache_key(headings, "some-model", mode="llm_full")
    asker = _asker(tmp_path)
    assert asker.cache_path(headings) == tmp_path / f"{key}.json"
    assert asker.cache_path(headings, at=7) == tmp_path / f"{key}-at7.json"
    assert _asker(None).cache_path(headings) is None


def test_an_answer_is_cached_and_replayed(tmp_path: Path) -> None:
    headings = _extract_headings(_MD)
    assert _asker(tmp_path).ask(headings) == ("1: 1\n2: 2", False)

    def must_not_run(_prompt: str) -> str:
        raise AssertionError("the cached answer should be used")

    assert _asker(tmp_path, must_not_run).ask(headings) == ("1: 1\n2: 2", True)
    saved = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert saved["mode"] == "llm_full" and saved["model"] == "some-model"


def test_a_failed_call_is_none_and_caches_nothing(tmp_path: Path) -> None:
    def fails(_prompt: str) -> str:
        raise RuntimeError("backend down")

    assert _asker(tmp_path, fails).ask(_extract_headings(_MD)) is None
    assert list(tmp_path.iterdir()) == []


def test_an_unreadable_cache_file_is_no_answer(tmp_path: Path) -> None:
    bad = tmp_path / "x.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _read_cached_response(bad) is None
    assert _read_cached_response(tmp_path / "missing.json") is None
    assert _read_cached_response(None) is None


@pytest.mark.parametrize(
    ("mode", "slug", "version"),
    [
        ("llm", "heading_normalize", HEADING_NORMALIZE_PROMPT_VERSION),
        ("llm_full", "heading_normalize_full", HEADING_NORMALIZE_FULL_PROMPT_VERSION),
        ("llm_dehead", "heading_normalize_dehead", HEADING_NORMALIZE_DEHEAD_PROMPT_VERSION),
    ],
)
def test_each_mode_asks_its_own_prompt(mode, slug: str, version: int) -> None:
    request = _mode_request(_MD, _extract_headings(_MD), mode=mode, max_input_tokens=None)
    assert (request.agent_slug, request.prompt_version) == (slug, version)
    assert "Setup" in request.prompt
