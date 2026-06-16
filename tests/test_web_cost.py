from __future__ import annotations

from pagespeak.web._cost import (
    cache_miss_count,
    gate_decision,
    vision_will_run,
)


def test_cache_miss_count_unreadable_image_counts_as_miss(tmp_path):
    # A non-image file must NOT raise (compute_phash raises on it) — it counts
    # as an uncached miss, the conservative direction. Guards the live gate
    # against a 500 on an unreadable extracted image.
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "bad.png").write_bytes(b"not an image")
    res = cache_miss_count(tmp_path)
    assert res == (1, 0, 1)


def test_vision_will_run_truth_table():
    assert vision_will_run(None, None, diagrams=True, cache_only=False) is True
    assert vision_will_run(None, None, diagrams=True, cache_only=True) is False
    assert vision_will_run(None, None, diagrams=False, cache_only=False) is False
    assert vision_will_run("ingest", "cleanup", diagrams=True, cache_only=False) is False
    assert vision_will_run("split", "split", diagrams=True, cache_only=False) is False
    assert vision_will_run("vision", "vision", diagrams=True, cache_only=False) is True


def test_cache_miss_count_none_when_no_images(tmp_path):
    assert cache_miss_count(tmp_path) is None


def test_cache_miss_count_counts(tmp_path, monkeypatch):
    import pagespeak.web._cost as cost

    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"a")
    (tmp_path / "images" / "b.png").write_bytes(b"b")
    cache = tmp_path / ".vision-cache"
    cache.mkdir()
    monkeypatch.setattr(cost, "compute_phash", lambda p: p.stem)
    (cache / "a.json").write_text("{}", encoding="utf-8")

    res = cache_miss_count(tmp_path)
    assert res == (2, 1, 1)


def test_gate_decision_no_gate_when_vision_not_running():
    d = gate_decision(out_dir=None, will_run=False, backend="claude_code", confirmed=False)
    assert d.needs_confirm is False and d.blocked is False


def test_gate_decision_paid_unknown_is_blocked(tmp_path):
    d = gate_decision(out_dir=tmp_path, will_run=True, backend="openrouter", confirmed=False)
    assert d.blocked is True


def test_gate_decision_claude_code_unknown_needs_confirm(tmp_path):
    d = gate_decision(out_dir=tmp_path, will_run=True, backend="claude_code", confirmed=False)
    assert d.needs_confirm is True and d.blocked is False


def test_gate_decision_confirmed_passes(tmp_path):
    d = gate_decision(out_dir=tmp_path, will_run=True, backend="claude_code", confirmed=True)
    assert d.needs_confirm is False and d.blocked is False
