"""Tests for pagespeak._diagrams — backend protocol, both implementations,
JSON parser, and markdown rewrite."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pagespeak import Diagram, IngestResult
from pagespeak.services._diagrams import (
    CLAUDE_CODE_TIMEOUT_S_DEFAULT,
    DEFAULT_VISION_CONCURRENCY,
    AnthropicVisionBackend,
    ClaudeCodeVisionBackend,
    OpenRouterVisionBackend,
    VisionParseError,
    _build_diagram,
    _claude_code_timeout_s,
    _inject_diagrams,
    _parse_response,
    _resolve_concurrency,
    build_backend,
    enrich_with_diagrams,
    gather_diagrams,
    inject_diagrams,
)


def _mock_anthropic_client(payload: dict) -> MagicMock:
    """Mock pf-core AnthropicClient with a canned chat() response."""
    client = MagicMock()
    client.chat.return_value = (
        json.dumps(payload),
        {"prompt_tokens": 0, "completion_tokens": 0},
    )
    return client


# --- _parse_response (handles fenced + preamble + raw JSON) -------------


def test_parse_response_diagram() -> None:
    text = json.dumps(
        {
            "is_diagram": True,
            "diagram_type": "sequence",
            "caption": "Auth handshake.",
            "mermaid": "sequenceDiagram\n  A->>B: hi",
        }
    )
    parsed = _parse_response(text, Path("img.png"))
    assert parsed["is_diagram"] is True
    assert parsed["caption"] == "Auth handshake."
    assert parsed["mermaid"].startswith("sequenceDiagram")


def test_parse_response_non_diagram_drops_mermaid() -> None:
    text = json.dumps(
        {
            "is_diagram": False,
            "diagram_type": None,
            "caption": "A photograph.",
            "mermaid": "should be dropped",
        }
    )
    parsed = _parse_response(text, Path("img.png"))
    assert parsed["mermaid"] is None
    assert parsed["caption"] == "A photograph."


def test_parse_response_strips_markdown_fences() -> None:
    text = "```json\n" + json.dumps({"is_diagram": False, "caption": "x"}) + "\n```"
    parsed = _parse_response(text, Path("img.png"))
    assert parsed["caption"] == "x"


def test_parse_response_extracts_json_from_preamble() -> None:
    # Claude Code may include "I'll analyze this image..." text before the JSON.
    text = (
        "I'll read the image and analyze it.\n\n"
        + json.dumps({"is_diagram": True, "caption": "x", "mermaid": "g"})
        + "\n\nHope that helps!"
    )
    parsed = _parse_response(text, Path("img.png"))
    assert parsed["caption"] == "x"
    assert parsed["mermaid"] == "g"


def test_parse_response_invalid_json_falls_back() -> None:
    parsed = _parse_response("not json at all", Path("img.png"))
    assert parsed["is_diagram"] is False
    assert parsed["mermaid"] is None
    assert "img.png" in parsed["caption"]


# --- _inject_diagrams ----------------------------------------------------


def test_inject_diagrams_puts_caption_in_alt_text() -> None:
    md = "Some text.\n\n![](images/foo.png)\n\nMore text."
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="A flowchart.",
            mermaid="flowchart TD\n  A-->B",
        )
    }
    out = _inject_diagrams(md, diagrams)
    assert "![A flowchart.](images/foo.png)" in out


def test_inject_diagrams_drops_italic_caption_block() -> None:
    md = "![](images/foo.png)"
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="A flowchart.",
            mermaid="flowchart TD\n  A-->B",
        )
    }
    out = _inject_diagrams(md, diagrams)
    assert "*A flowchart.*" not in out


def test_inject_diagrams_tags_mermaid_with_source_path() -> None:
    md = "![](images/foo.png)"
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="A flowchart.",
            mermaid="flowchart TD\n  A-->B",
        )
    }
    out = _inject_diagrams(md, diagrams)
    assert '```mermaid pagespeak-image="images/foo.png"' in out
    assert "flowchart TD" in out


def test_inject_diagrams_non_diagram_alt_only_no_mermaid() -> None:
    md = "![](images/photo.png)"
    diagrams = {
        "photo.png": Diagram(
            image_path=Path("images/photo.png"),
            caption="Decorative photo.",
            mermaid=None,
        )
    }
    out = _inject_diagrams(md, diagrams)
    assert "![Decorative photo.](images/photo.png)" in out
    assert "```mermaid" not in out


def test_inject_diagrams_escapes_brackets_in_caption() -> None:
    md = "![](images/foo.png)"
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="See [Section 1] for details.",
            mermaid=None,
        )
    }
    out = _inject_diagrams(md, diagrams)
    # Brackets become parens so the alt-text syntax stays valid.
    assert "![See (Section 1) for details.](images/foo.png)" in out


def test_inject_diagrams_collapses_caption_newlines() -> None:
    md = "![](images/foo.png)"
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="Line one.\nLine two.",
            mermaid=None,
        )
    }
    out = _inject_diagrams(md, diagrams)
    assert "![Line one. Line two.](images/foo.png)" in out


def test_inject_diagrams_leaves_unknown_images_alone() -> None:
    md = "![](images/unknown.png)"
    out = _inject_diagrams(md, {})
    assert out == md


# --- _inject_diagrams: faithful mode (preserve_alt) ---------------------


def test_inject_preserve_alt_keeps_original_alt_and_adds_mermaid() -> None:
    """Faithful mode: the publisher's alt is kept verbatim and only the Mermaid
    block is appended; the vision caption is NOT injected."""
    md = "![Original publisher alt.](images/foo.png)"
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="A vision-enriched caption that must not appear.",
            mermaid="flowchart TD\n  A-->B",
        )
    }
    out = _inject_diagrams(md, diagrams, preserve_alt=True)
    assert "![Original publisher alt.](images/foo.png)" in out
    assert "vision-enriched caption" not in out
    assert '```mermaid pagespeak-image="images/foo.png"' in out
    assert "flowchart TD" in out


def test_inject_preserve_alt_non_diagram_leaves_ref_untouched() -> None:
    """Faithful mode adds nothing to a non-diagram figure (no Mermaid)."""
    md = "![Original alt.](images/photo.png)"
    diagrams = {
        "photo.png": Diagram(
            image_path=Path("images/photo.png"),
            caption="Decorative photo.",
            mermaid=None,
        )
    }
    out = _inject_diagrams(md, diagrams, preserve_alt=True)
    assert out == md


def test_inject_preserve_alt_empty_alt_stays_empty_with_mermaid() -> None:
    """A figure with no alt keeps its empty alt (no caption) and gets Mermaid."""
    md = "![](images/foo.png)"
    diagrams = {
        "foo.png": Diagram(
            image_path=Path("images/foo.png"),
            caption="A flowchart.",
            mermaid="flowchart TD\n  A-->B",
        )
    }
    out = _inject_diagrams(md, diagrams, preserve_alt=True)
    assert "![](images/foo.png)" in out
    assert "A flowchart." not in out
    assert "flowchart TD" in out


# --- AnthropicVisionBackend ---------------------------------------------


def test_anthropic_backend_analyze_calls_client(fake_image: Path) -> None:
    """The pf-core AnthropicClient's chat() is called with the resolved
    model and a multimodal Anthropic-format message list."""
    client = _mock_anthropic_client(
        {
            "is_diagram": True,
            "diagram_type": "flowchart",
            "caption": "Test diagram.",
            "mermaid": "flowchart TD\n  A-->B",
        }
    )
    backend = AnthropicVisionBackend(client=client, model="test-model")
    diagram = backend.analyze(fake_image)
    assert diagram.caption == "Test diagram."
    assert diagram.mermaid == "flowchart TD\n  A-->B"
    assert diagram.diagram_type == "flowchart"
    client.chat.assert_called_once()
    call_kwargs = client.chat.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    # The image block uses Anthropic's "image" / "source" schema (not
    # OpenRouter's "image_url").
    messages = call_kwargs["messages"]
    content = messages[0]["content"]
    types = [item["type"] for item in content]
    assert "image" in types
    image_block = next(c for c in content if c["type"] == "image")
    assert image_block["source"]["type"] == "base64"


def test_anthropic_backend_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an injected client and without ANTHROPIC_API_KEY, the
    backend raises a clear RuntimeError mirroring the OpenRouter pattern."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Anthropic backend requires an API key"):
        AnthropicVisionBackend()


def test_anthropic_backend_uses_env_var_api_key(fake_image: Path) -> None:
    """When no `client` is injected, the backend reads `ANTHROPIC_API_KEY`
    from env and builds a pf-core AnthropicClient with it."""
    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}),
        patch("pf_core.clients.anthropic.AnthropicClient") as MockClient,
    ):
        instance = MockClient.return_value
        instance.chat.return_value = (
            json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}),
            {},
        )
        AnthropicVisionBackend().analyze(fake_image)
    MockClient.assert_called_once()
    assert MockClient.call_args.kwargs["api_key"] == "env-key"


# --- ClaudeCodeVisionBackend --------------------------------------------


def _mock_claude_client(content: str) -> MagicMock:
    """Mock pf-core ClaudeCodeClient with a canned chat() response."""
    client = MagicMock()
    client.chat.return_value = (content, {"prompt_tokens": 0, "completion_tokens": 0})
    return client


def test_claude_code_backend_constructs_prompt_with_path(
    fake_image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PAGESPEAK_VISION_MODEL", raising=False)
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    backend.analyze(fake_image)
    call_kwargs = client.chat.call_args.kwargs
    messages = call_kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    prompt = messages[0]["content"]
    assert str(fake_image.resolve()) in prompt
    assert "Read the image at" in prompt


def test_claude_code_backend_passes_explicit_model_when_unset(
    fake_image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cost-protection regression: with no `model=` arg and no env var
    override, the backend MUST pass an explicit, non-empty `model`
    kwarg to `client.chat()` (resolved from `config/model_router.yaml`).
    Without an explicit model, pf-core's ClaudeCodeClient lets the
    active session decide — on Claude Max that's Sonnet/Opus, and a
    1000-image vision pass quietly burns a day's premium usage.

    Value-agnostic on purpose: the guarantee is "SOME explicit model is
    passed instead of deferring to the session", NOT a specific slug —
    asserting the live YAML's current model literal is a brittle config
    coupling, not a behaviour test."""
    monkeypatch.delenv("PAGESPEAK_VISION_MODEL", raising=False)
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    backend.analyze(fake_image)
    kwargs = client.chat.call_args.kwargs
    assert "model" in kwargs, "no explicit model passed → session default (Sonnet/Opus) billed"
    assert isinstance(kwargs["model"], str) and kwargs["model"], "model kwarg empty"


def test_claude_code_backend_ignores_legacy_env_model_var(
    fake_image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PAGESPEAK_VISION_MODEL` env var is no longer consulted.
    YAML is the single source of truth; env vars only pick the backend.
    Setting the legacy env var has no effect on the resolved model.

    Value-agnostic: asserts the env value is NOT what got used (the real
    regression guard), without coupling to the live YAML's model
    literal."""
    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "haiku-from-env")
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    backend.analyze(fake_image)
    resolved = client.chat.call_args.kwargs["model"]
    assert resolved != "haiku-from-env"


def test_claude_code_backend_explicit_model_wins_over_env(
    fake_image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit `model=` arg always wins — the per-call override path is
    preserved as the highest-precedence model selector."""
    monkeypatch.setenv("PAGESPEAK_VISION_MODEL", "haiku-from-env")
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(
        claude_bin="/fake/claude", model="explicit-model", client=client
    )
    backend.analyze(fake_image)
    assert client.chat.call_args.kwargs["model"] == "explicit-model"


def test_claude_code_backend_passes_model_flag(fake_image: Path) -> None:
    """The resolved model must propagate to `client.chat(model=...)` so
    users can downgrade from their default (often Opus) to Haiku for
    cheap batch vision passes. pf-core's ClaudeCodeClient.chat() then
    threads it through as `claude --print --model X`."""
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(
        claude_bin="/fake/claude",
        model="claude-haiku-4-5-20251001",
        client=client,
    )
    backend.analyze(fake_image)
    assert client.chat.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"
    # The prompt is still in the user message content.
    messages = client.chat.call_args.kwargs["messages"]
    assert "Read the image at" in messages[0]["content"]


def test_claude_code_factory_propagates_model_to_backend() -> None:
    """`build_backend('claude_code', model=…)` must wire model through to
    the constructed backend (was a no-op)."""
    with patch("pagespeak.services._vision_backends.shutil.which", return_value="/fake/claude"):
        backend = build_backend("claude_code", model="claude-haiku-4-5-20251001")
    assert isinstance(backend, ClaudeCodeVisionBackend)
    assert backend._model == "claude-haiku-4-5-20251001"


# --- gather_diagrams: preflight gated on real work (cache-miss) ----------


class _RecordingDeadBackend:
    """A backend whose preflight + analyze both fail (a revoked/invalid
    key) and count their calls — so a test can assert neither ran on a
    fully-cached pass."""

    def __init__(self) -> None:
        self.preflight_calls = 0
        self.analyze_calls = 0

    def preflight_check(self) -> None:
        self.preflight_calls += 1
        raise RuntimeError("dead key (401)")

    def analyze(
        self, image_path: Path, *, phash: str | None = None, original_alt: str | None = None
    ) -> Diagram:
        self.analyze_calls += 1
        raise RuntimeError("dead key (401)")


class _PrimingBackend:
    """Cache-priming backend: analyze returns a real Diagram; no preflight."""

    def analyze(
        self, image_path: Path, *, phash: str | None = None, original_alt: str | None = None
    ) -> Diagram:
        return Diagram(image_path=image_path, caption="primed", mermaid=None)


def _phashable_image(path: Path) -> Path:
    """Write a small real PNG that `compute_phash` can read (the conftest
    1x1 `fake_image` is too degenerate to phash, so its cache key can't be
    computed)."""
    from PIL import Image

    Image.new("RGB", (16, 16), color="white").save(path)
    return path


def test_gather_skips_preflight_when_all_cached(tmp_path: Path) -> None:
    """A fully-cached vision pass makes zero API calls, so the auth
    preflight MUST be skipped — the run succeeds even with a backend whose
    preflight (and analyze) would fail. Regression for the stranded-cache
    bug: an invalid/revoked key blocked reuse of a prior backend's cache.
    """
    img = _phashable_image(tmp_path / "img.png")
    cache_dir = tmp_path / "vcache"
    # Prime the cache with a working backend.
    gather_diagrams([img], backend=_PrimingBackend(), backend_name="anthropic", cache_dir=cache_dir)
    # Now a dead backend: every image is cached, so neither preflight nor
    # analyze may run.
    dead = _RecordingDeadBackend()
    out = gather_diagrams([img], backend=dead, backend_name="anthropic", cache_dir=cache_dir)
    assert img.name in out  # served from cache
    assert dead.preflight_calls == 0  # preflight skipped — no live work
    assert dead.analyze_calls == 0  # no live call


def test_gather_reuses_cache_across_backend(tmp_path: Path) -> None:
    """A description cached under one engine is reused on a later pass that
    names a DIFFERENT engine — no preflight, no re-analysis. The image's
    phash is the cache key; the engine name is provenance, not a gate."""
    img = _phashable_image(tmp_path / "img.png")
    cache_dir = tmp_path / "vcache"
    # Prime under openrouter (the cross-engine cache-reuse case).
    gather_diagrams(
        [img], backend=_PrimingBackend(), backend_name="openrouter", cache_dir=cache_dir
    )
    # Re-gather naming claude_code with a dead backend: every image is
    # already cached, so neither preflight nor analyze may run.
    dead = _RecordingDeadBackend()
    out = gather_diagrams([img], backend=dead, backend_name="claude_code", cache_dir=cache_dir)
    assert img.name in out  # served from the openrouter-stamped cache
    assert dead.preflight_calls == 0  # no live work → preflight skipped
    assert dead.analyze_calls == 0  # reused, not re-analyzed under the new engine


def test_gather_runs_preflight_when_a_cache_miss_exists(tmp_path: Path) -> None:
    """When ≥1 image is a cache miss there IS real work, so the preflight
    runs (fail-fast) and its failure propagates."""
    img = _phashable_image(tmp_path / "img.png")
    dead = _RecordingDeadBackend()
    with pytest.raises(RuntimeError, match="dead key"):
        gather_diagrams([img], backend=dead, backend_name="anthropic", cache_dir=tmp_path / "empty")
    assert dead.preflight_calls == 1


def test_claude_code_backend_parses_json_response(fake_image: Path) -> None:
    client = _mock_claude_client(
        json.dumps(
            {
                "is_diagram": True,
                "diagram_type": "flowchart",
                "caption": "Flow.",
                "mermaid": "flowchart TD\n  A-->B",
            }
        )
    )
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    diagram = backend.analyze(fake_image)
    assert diagram.caption == "Flow."
    assert diagram.mermaid == "flowchart TD\n  A-->B"


def test_claude_code_backend_parses_fenced_json(fake_image: Path) -> None:
    payload = json.dumps({"is_diagram": False, "caption": "y", "mermaid": None})
    client = _mock_claude_client(f"Here you go:\n\n```json\n{payload}\n```")
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    diagram = backend.analyze(fake_image)
    assert diagram.caption == "y"
    assert diagram.mermaid is None


def test_claude_code_backend_raises_when_binary_missing() -> None:
    with (
        patch("pagespeak.services._vision_backends.shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="Claude Code CLI not found"),
    ):
        ClaudeCodeVisionBackend()


def test_claude_code_backend_raises_on_subprocess_failure(fake_image: Path) -> None:
    """When pf-core's ClaudeCodeClient.chat() raises (subprocess exit-1
    after pf-core's internal retry loop has exhausted its attempts), the
    backend wraps it in a RuntimeError preserving the contract."""
    from pf_core.exceptions import AppError

    client = MagicMock()
    err = AppError(
        "claude --print exited 1: boom", context={"returncode": 1, "stderr_head": "boom"}
    )
    client.chat.side_effect = err
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    with pytest.raises(RuntimeError, match="claude --print exited 1"):
        backend.analyze(fake_image)


# --- visibility regressions ----------------------------------------


def test_claude_code_backend_logs_resolved_model_on_init(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Phase 1 visibility: every `ClaudeCodeVisionBackend.__init__` must
    emit one INFO line naming the resolved model + bin so end-to-end
    runs surface the actual model in use without a debug pass.
    resolved-model now comes from YAML (env vars ignored), so we assert
    against the explicit constructor arg path."""
    with caplog.at_level("INFO", logger="pagespeak.services._diagrams"):
        ClaudeCodeVisionBackend(
            claude_bin="/fake/claude", model="explicit-log-model", client=MagicMock()
        )
    matches = [r for r in caplog.records if "claude_code_vision_backend_initialized" in r.message]
    assert matches, "init log line missing from caplog"
    record = matches[0]
    assert "model=explicit-log-model" in record.message
    assert "bin=/fake/claude" in record.message


def test_claude_code_backend_failure_message_includes_stdout_and_stderr(
    fake_image: Path,
) -> None:
    """Phase 1 visibility: failure RuntimeError must surface both stdout
    AND stderr (truncated) and the resolved model. The earlier message
    only carried `stderr[:200]`, which on quota-style failures was
    typically empty — leaving the user with no diagnostic information.
    pf-core's ClaudeCodeError carries `stderr_head` in context; the
    AppError message itself carries the rest (subprocess stdout)."""
    from pf_core.exceptions import AppError

    client = MagicMock()
    client.chat.side_effect = AppError(
        '`claude --print` exited 1: {"error": "rate_limit_exceeded"}',
        context={"returncode": 1, "stderr_head": "usage exceeded"},
    )
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", model="my-model", client=client)
    with pytest.raises(RuntimeError) as exc_info:
        backend.analyze(fake_image)
    msg = str(exc_info.value)
    assert "model=my-model" in msg
    assert "rate_limit_exceeded" in msg  # from AppError message (stdout-equivalent)
    assert "usage exceeded" in msg  # from context.stderr_head


def test_claude_code_backend_constructs_pf_core_client_with_retry_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract test (pf-core retry adoption): when pagespeak builds its
    own `ClaudeCodeClient` (caller didn't inject one), it must pass
    `retry=1` so pf-core retries transient failures internally — the
    earlier retry-once behavior now lives inside pf-core. Without
    `retry=1` we silently lose resilience against rate-limit windows
    and momentary auth refreshes."""
    monkeypatch.setattr(
        "pagespeak.services._vision_backends.shutil.which", lambda _: "/fake/claude"
    )
    with patch("pf_core.clients.claude_code.ClaudeCodeClient") as ctor:
        ctor.return_value = MagicMock()
        ClaudeCodeVisionBackend(model="m")
    assert ctor.call_count == 1
    kwargs = ctor.call_args.kwargs
    assert kwargs.get("retry") == 1, (
        f"pagespeak must construct pf-core's ClaudeCodeClient with retry=1; got kwargs={kwargs}"
    )


def test_gather_diagrams_emits_failure_summary_at_warning_below_25_percent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Phase 1 alarming: low failure rate logs at WARNING (visible but
    not panic-worthy)."""
    images = [tmp_path / f"img_{i}.png" for i in range(20)]
    for img in images:
        img.write_bytes(b"x")

    def maybe_fail(image_path: Path, **_kw: object) -> Diagram:
        # 2/20 = 10%, below the 25% ERROR threshold.
        if image_path.name in {"img_0.png", "img_1.png"}:
            raise RuntimeError("boom")
        return Diagram(image_path=image_path, caption="ok", mermaid=None)

    backend = MagicMock()
    backend.analyze.side_effect = maybe_fail

    with caplog.at_level("WARNING", logger="pagespeak.services._diagrams"):
        gather_diagrams(images, backend=backend, concurrency=4)
    summary = [r for r in caplog.records if "vision_failure_summary" in r.message]
    assert summary, "summary log line missing"
    assert summary[-1].levelname == "WARNING"
    assert "failures=2/20" in summary[-1].message


def test_gather_diagrams_emits_failure_summary_at_error_above_25_percent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Phase 1 alarming: catastrophic failure rate (≥25%) escalates to
    ERROR so a >97%-failure run lights up immediately rather than buried
    in 1180 WARNINGs."""
    images = [tmp_path / f"img_{i}.png" for i in range(8)]
    for img in images:
        img.write_bytes(b"x")

    backend = MagicMock()
    backend.analyze.side_effect = RuntimeError("everything is broken")

    with caplog.at_level("ERROR", logger="pagespeak.services._diagrams"):
        gather_diagrams(images, backend=backend, concurrency=4)
    errors = [r for r in caplog.records if "vision_failure_summary" in r.message]
    assert errors, "ERROR-level summary missing"
    assert errors[-1].levelname == "ERROR"
    assert "failures=8/8" in errors[-1].message
    assert "rate=100.0%" in errors[-1].message


def test_gather_diagrams_emits_zero_failures_summary(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A clean run still emits one INFO summary so the absence of failures
    is recorded explicitly (silence ≠ success in log review)."""
    images = [tmp_path / f"img_{i}.png" for i in range(3)]
    for img in images:
        img.write_bytes(b"x")

    backend = MagicMock()
    backend.analyze.side_effect = lambda p, **_kw: Diagram(
        image_path=p, caption=f"ok-{p.name}", mermaid=None
    )

    with caplog.at_level("INFO", logger="pagespeak.services._diagrams"):
        gather_diagrams(images, backend=backend, concurrency=2)
    summary = [r for r in caplog.records if "vision_failure_summary" in r.message]
    assert summary, "summary log missing on clean run"
    assert summary[-1].levelname == "INFO"
    assert "failures=0/3" in summary[-1].message


# --- Claude Code preflight ----------------------------------------


def test_claude_code_preflight_check_delegates_to_client_preflight() -> None:
    """preflight_check is a 1-liner over pf-core's ClaudeCodeClient.preflight().
    The pf-core method handles the chat-call internals, error formatting,
    and the `/login` remediation message. Pagespeak's job is just to call it."""
    client = MagicMock()
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", model="m", client=client)
    backend.preflight_check()
    client.preflight.assert_called_once_with()


def test_claude_code_preflight_check_propagates_pf_core_errors() -> None:
    """pf-core's ClaudeCodeClient.preflight() raises ClaudeCodeError with an
    actionable `/login` remediation message. Pagespeak's preflight_check lets
    the error propagate unchanged — it's already the right shape."""
    from pf_core.exceptions import AppError

    client = MagicMock()
    client.preflight.side_effect = AppError(
        "Claude Code preflight failed (binary=/fake/claude, model=m). "
        "Most likely the session needs to be re-authenticated:\n\n"
        "    /fake/claude /login\n\n"
        "Underlying error: Not logged in",
        context={"preflight": True},
    )
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", model="m", client=client)
    with pytest.raises(AppError) as exc_info:
        backend.preflight_check()
    msg = str(exc_info.value)
    assert "preflight failed" in msg
    assert "/login" in msg


def test_gather_diagrams_calls_preflight_when_backend_exposes_it(
    tmp_path: Path,
) -> None:
    """`gather_diagrams` must call `preflight_check()` on backends that
    expose it (currently only ClaudeCodeVisionBackend), before the
    ThreadPool fanout."""
    images = [tmp_path / "img.png"]
    images[0].write_bytes(b"x")

    backend = MagicMock(spec=["analyze", "preflight_check"])
    backend.analyze.return_value = Diagram(image_path=images[0], caption="ok", mermaid=None)

    gather_diagrams(images, backend=backend, concurrency=1)
    backend.preflight_check.assert_called_once()


def test_gather_diagrams_skips_preflight_when_backend_lacks_method(
    tmp_path: Path,
) -> None:
    """Backends without `preflight_check` (raw test mocks, third-party
    backends) skip preflight cleanly — duck-typed via getattr. (All three
    built-in vision backends — Anthropic, ClaudeCode, OpenRouter — DO
    expose preflight_check; this test verifies the dispatch contract for
    backends that don't.)"""
    images = [tmp_path / "img.png"]
    images[0].write_bytes(b"x")

    backend = MagicMock(spec=["analyze"])  # NO preflight_check
    backend.analyze.return_value = Diagram(image_path=images[0], caption="ok", mermaid=None)

    # Should not raise AttributeError.
    result = gather_diagrams(images, backend=backend, concurrency=1)
    assert result["img.png"].caption == "ok"


def test_gather_diagrams_preflight_failure_aborts_before_fanout(
    tmp_path: Path,
) -> None:
    """A failed preflight must raise BEFORE any per-image call fires —
    the whole point is to short-circuit the 1180-call doomed batch."""
    images = [tmp_path / f"img_{i}.png" for i in range(20)]
    for img in images:
        img.write_bytes(b"x")

    backend = MagicMock(spec=["analyze", "preflight_check"])
    backend.preflight_check.side_effect = RuntimeError("preflight failed: not logged in")
    backend.analyze.return_value = Diagram(image_path=images[0], caption="ok", mermaid=None)

    with pytest.raises(RuntimeError, match="preflight failed"):
        gather_diagrams(images, backend=backend, concurrency=4)
    # Fanout never started.
    backend.analyze.assert_not_called()


def test_gather_diagrams_no_preflight_when_no_images(tmp_path: Path) -> None:
    """`gather_diagrams([])` early-returns before constructing or
    calling the backend. Preflight must NOT fire on the no-images path."""
    backend = MagicMock(spec=["analyze", "preflight_check"])
    result = gather_diagrams([], backend=backend)
    assert result == {}
    backend.preflight_check.assert_not_called()


# --- build_backend factory + enrich_with_diagrams -----------------------


def test_build_backend_factory_anthropic() -> None:
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        backend = build_backend("anthropic", model="m")
    assert isinstance(backend, AnthropicVisionBackend)


def test_build_backend_factory_claude_code() -> None:
    with patch("pagespeak.services._vision_backends.shutil.which", return_value="/fake/claude"):
        backend = build_backend("claude_code")
    assert isinstance(backend, ClaudeCodeVisionBackend)


def test_build_backend_factory_openrouter() -> None:
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        backend = build_backend("openrouter", model="google/gemini-2.0-flash-exp")
    assert isinstance(backend, OpenRouterVisionBackend)


# --- OpenRouterVisionBackend ---------------------------------------------


def _mock_openrouter_client(payload: dict) -> MagicMock:
    """Mock pf-core OpenRouterClient with a canned chat() response."""
    client = MagicMock()
    client.chat.return_value = (json.dumps(payload), {"prompt_tokens": 0, "completion_tokens": 0})
    return client


def test_openrouter_backend_raises_when_api_key_missing() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(RuntimeError, match="OpenRouter backend requires an API key"),
    ):
        OpenRouterVisionBackend()


def test_openrouter_backend_uses_env_var_api_key(fake_image: Path) -> None:
    """When no `client` is injected, the backend reads `OPENROUTER_API_KEY`
    from env and builds a pf-core OpenRouterClient with it."""
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-key"}),
        patch("pf_core.clients.openrouter.OpenRouterClient") as MockClient,
    ):
        instance = MockClient.return_value
        instance.chat.return_value = (
            json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}),
            {},
        )
        OpenRouterVisionBackend().analyze(fake_image)
    MockClient.assert_called_once()
    assert MockClient.call_args.kwargs["api_key"] == "env-key"


def test_openrouter_backend_constructs_openai_style_image_payload(
    fake_image: Path,
) -> None:
    client = _mock_openrouter_client({"is_diagram": False, "caption": "x", "mermaid": None})
    backend = OpenRouterVisionBackend(api_key="k", client=client)
    backend.analyze(fake_image)
    messages = client.chat.call_args.kwargs["messages"]
    content = messages[0]["content"]
    types = [item["type"] for item in content]
    assert "image_url" in types  # OpenAI-style, not Anthropic's "image"
    image_url = next(c for c in content if c["type"] == "image_url")
    assert image_url["image_url"]["url"].startswith("data:image/")


def test_openrouter_backend_uses_yaml_model_when_arg_unset(fake_image: Path) -> None:
    """Model resolution goes through `resolve_agent_config` —
    YAML at `config/model_router.yaml` (`agents.vision.backends.openrouter.model`)
    wins. Repo YAML pins `google/gemini-2.5-flash` for openrouter, so an
    OpenRouterVisionBackend with no explicit `model=` picks that up.

    The previous behavior (hardcoded `anthropic/claude-haiku-4.5` fallback)
    silently shadowed the YAML — this test pins the corrected behavior."""
    client = _mock_openrouter_client({"is_diagram": False, "caption": "x", "mermaid": None})
    backend = OpenRouterVisionBackend(api_key="k", client=client)
    backend.analyze(fake_image)
    assert client.chat.call_args.kwargs["model"] == "google/gemini-2.5-flash"


def test_openrouter_backend_falls_back_to_default_when_yaml_absent(
    fake_image: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no config resolves — MODEL_ROUTER_CONFIG points at a missing
    file, so neither the cwd config nor the packaged default is read — the
    backend's hardcoded `DEFAULT_MODEL` (`anthropic/claude-haiku-4.5`) is
    used. Cost-protection guard for a genuinely config-less environment."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_ROUTER_CONFIG", str(tmp_path / "missing.yaml"))
    client = _mock_openrouter_client({"is_diagram": False, "caption": "x", "mermaid": None})
    backend = OpenRouterVisionBackend(api_key="k", client=client)
    backend.analyze(fake_image)
    assert client.chat.call_args.kwargs["model"] == "anthropic/claude-haiku-4.5"


def test_openrouter_backend_overrides_model_via_param(fake_image: Path) -> None:
    client = _mock_openrouter_client({"is_diagram": False, "caption": "x", "mermaid": None})
    backend = OpenRouterVisionBackend(
        api_key="k", model="google/gemini-2.0-flash-exp", client=client
    )
    backend.analyze(fake_image)
    assert client.chat.call_args.kwargs["model"] == "google/gemini-2.0-flash-exp"


def test_openrouter_backend_parses_chat_completions_response(
    fake_image: Path,
) -> None:
    client = _mock_openrouter_client(
        {
            "is_diagram": True,
            "diagram_type": "flowchart",
            "caption": "Auth flow.",
            "mermaid": "flowchart TD\n  A-->B",
        }
    )
    backend = OpenRouterVisionBackend(api_key="k", client=client)
    diagram = backend.analyze(fake_image)
    assert diagram.caption == "Auth flow."
    assert diagram.mermaid == "flowchart TD\n  A-->B"


def test_build_backend_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown vision_backend"):
        build_backend("nope")  # type: ignore[arg-type]


def test_enrich_with_diagrams_handles_extraction_failure(fake_image: Path) -> None:
    # Mock a backend whose analyze() always raises.
    backend = MagicMock()
    backend.analyze.side_effect = RuntimeError("api down")

    result = IngestResult(markdown=f"![](images/{fake_image.name})", images=[fake_image])
    out = enrich_with_diagrams(result, backend=backend)
    assert len(out.diagrams) == 1
    assert out.diagrams[0].mermaid is None
    assert "extraction failed" in out.diagrams[0].caption


def test_enrich_with_diagrams_no_images_is_noop() -> None:
    result = IngestResult(markdown="hi", images=[])
    out = enrich_with_diagrams(result, backend=MagicMock())
    assert out is result
    assert out.diagrams == []


# --- parallel vision pass ---------------------------------------


def test_resolve_concurrency_explicit_arg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_VISION_CONCURRENCY", "12")
    assert _resolve_concurrency(3) == 3


def test_resolve_concurrency_falls_back_to_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAGESPEAK_VISION_CONCURRENCY", "12")
    assert _resolve_concurrency(None) == 12


def test_resolve_concurrency_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGESPEAK_VISION_CONCURRENCY", raising=False)
    assert _resolve_concurrency(None) == DEFAULT_VISION_CONCURRENCY


def test_resolve_concurrency_invalid_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAGESPEAK_VISION_CONCURRENCY", "not-a-number")
    assert _resolve_concurrency(None) == DEFAULT_VISION_CONCURRENCY


def test_resolve_concurrency_clamps_to_minimum_one() -> None:
    assert _resolve_concurrency(0) == 1
    assert _resolve_concurrency(-5) == 1


def test_enrich_with_diagrams_runs_in_parallel(tmp_path: Path) -> None:
    """All images must be analyzed concurrently — verified by checking
    that no per-image work is serialized through a single thread.
    `analyze()` records its calling thread; with concurrency > 1 and
    multiple images we expect at least 2 distinct threads."""
    import threading

    # Create distinct fake images so per-image work has separate identity.
    images = []
    for i in range(6):
        img = tmp_path / f"img_{i}.png"
        # 1x1 transparent PNG (smallest valid).
        img.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        images.append(img)

    seen_threads: set[int] = set()
    barrier = threading.Barrier(6, timeout=2.0)

    def slow_analyze(image_path: Path, **_kw: object) -> Diagram:
        # Block until all 6 workers reach this point. If the executor
        # only runs one at a time, the barrier will time out — that's
        # the assertion the test is making.
        barrier.wait()
        seen_threads.add(threading.get_ident())
        return Diagram(image_path=image_path, caption=f"caption-{image_path.name}", mermaid=None)

    backend = MagicMock()
    backend.analyze.side_effect = slow_analyze

    result = IngestResult(
        markdown="\n".join(f"![](images/{p.name})" for p in images),
        images=images,
    )
    out = enrich_with_diagrams(result, backend=backend, concurrency=6)

    # All 6 ran; they did not serialize through a single thread.
    assert len(out.diagrams) == 6
    assert len(seen_threads) >= 2  # at least two threads were active concurrently


def test_enrich_with_diagrams_diagram_order_is_stable(tmp_path: Path) -> None:
    """`result.diagrams` is sorted by image basename so consumers and
    snapshot tests don't see thread-completion-order flakiness."""
    images = [tmp_path / f"img_{i:02}.png" for i in range(5)]
    for img in images:
        img.write_bytes(b"x")

    backend = MagicMock()
    backend.analyze.side_effect = lambda p, **_kw: Diagram(
        image_path=p, caption=p.name, mermaid=None
    )

    # Reverse the input list — sorted output should still be ascending.
    result = IngestResult(
        markdown="\n".join(f"![](images/{p.name})" for p in images),
        images=list(reversed(images)),
    )
    out = enrich_with_diagrams(result, backend=backend, concurrency=4)
    names = [d.image_path.name for d in out.diagrams]
    assert names == sorted(names)


def test_enrich_with_diagrams_one_image_failure_does_not_kill_others(
    tmp_path: Path,
) -> None:
    """A backend exception on one image leaves the other images
    successfully extracted, with the failure captured as a placeholder
    Diagram. Critical for long runs — one timeout shouldn't waste the
    rest."""
    images = [tmp_path / f"img_{i}.png" for i in range(4)]
    for img in images:
        img.write_bytes(b"x")

    def maybe_fail(image_path: Path, **_kw: object) -> Diagram:
        if image_path.name == "img_2.png":
            raise RuntimeError("api timeout on this one")
        return Diagram(image_path=image_path, caption=f"ok-{image_path.name}", mermaid=None)

    backend = MagicMock()
    backend.analyze.side_effect = maybe_fail

    result = IngestResult(
        markdown="\n".join(f"![](images/{p.name})" for p in images),
        images=images,
    )
    out = enrich_with_diagrams(result, backend=backend, concurrency=4)

    assert len(out.diagrams) == 4
    captions = {d.image_path.name: d.caption for d in out.diagrams}
    # Failed image got a placeholder caption.
    assert "extraction failed" in captions["img_2.png"]
    # Others succeeded.
    assert captions["img_0.png"] == "ok-img_0.png"
    assert captions["img_1.png"] == "ok-img_1.png"
    assert captions["img_3.png"] == "ok-img_3.png"


# --- vision failure: alt fallback, no cache, parse-error signalling ------


class _UnparseableBackend:
    """A backend whose model reply never parses — exercises the *real*
    parse path (not a mocked raise), reproducing the bug where a parse
    failure returned a plausible placeholder Diagram that got cached."""

    def analyze(
        self, image_path: Path, *, phash: str | None = None, original_alt: str | None = None
    ) -> Diagram:
        return _build_diagram(image_path, "not json at all")


def test_parse_response_flags_parse_failure() -> None:
    """An unparseable reply is flagged so the caller treats it as a failure
    (fall back to alt / skip cache) instead of caching the placeholder
    caption as a real description."""
    failed = _parse_response("not json at all", Path("img.png"))
    assert failed["parse_failed"] is True
    ok = _parse_response('{"is_diagram": false, "caption": "A cat."}', Path("img.png"))
    assert ok.get("parse_failed", False) is False


def test_build_diagram_raises_on_unparseable() -> None:
    """`_build_diagram` raises rather than returning a plausible placeholder
    Diagram, so the orchestrator routes the image to its failure handler."""
    with pytest.raises(VisionParseError):
        _build_diagram(Path("img.png"), "not json at all")


def test_gather_failure_falls_back_to_source_alt(fake_image: Path, tmp_path: Path) -> None:
    """A failed vision call with authored alt text captions the figure with
    that alt — a real description keeps it retrievable, not a dead marker."""
    backend = MagicMock()
    backend.analyze.side_effect = RuntimeError("api down")

    out = gather_diagrams(
        [fake_image],
        backend=backend,
        backend_name="anthropic",
        cache_dir=tmp_path / "cache",
        alt_by_basename={fake_image.name: "A labelled diagram of the cardiac cycle."},
    )
    assert out[fake_image.name].caption == "A labelled diagram of the cardiac cycle."


def test_gather_parse_failure_falls_back_and_skips_cache(tmp_path: Path) -> None:
    """A parse failure must not cache `(description unavailable)` as a real
    caption: it falls back to the authored alt and writes nothing to the
    cache, so a re-run re-attempts the real call.

    Uses a real (phash-decodable) PNG so the cache would genuinely be written
    on the old success-path — the empty-cache assertion has teeth."""
    from PIL import Image

    img = tmp_path / "fig.png"
    Image.new("RGB", (16, 16), (200, 100, 50)).save(img)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    out = gather_diagrams(
        [img],
        backend=_UnparseableBackend(),
        backend_name="anthropic",
        cache_dir=cache_dir,
        alt_by_basename={"fig.png": "A labelled diagram of the cardiac cycle."},
    )
    assert out["fig.png"].caption == "A labelled diagram of the cardiac cycle."
    assert list(cache_dir.glob("*.json")) == []


def test_gather_failure_no_alt_uses_clear_marker(fake_image: Path, tmp_path: Path) -> None:
    """With no alt to fall back on, the caption is a clearly-marked failure
    token — never a plausible sentence that reads as a real description."""
    backend = MagicMock()
    backend.analyze.side_effect = RuntimeError("api down")

    out = gather_diagrams(
        [fake_image],
        backend=backend,
        backend_name="anthropic",
        cache_dir=tmp_path / "cache",
    )
    assert "extraction failed" in out[fake_image.name].caption


def test_enrich_with_diagrams_concurrency_one_serializes(tmp_path: Path) -> None:
    """`concurrency=1` falls back to fully sequential — useful when the
    backend is sensitive to parallel calls."""
    import threading

    images = [tmp_path / f"img_{i}.png" for i in range(3)]
    for img in images:
        img.write_bytes(b"x")

    seen_threads: set[int] = set()

    def record_thread(image_path: Path, **_kw: object) -> Diagram:
        seen_threads.add(threading.get_ident())
        return Diagram(image_path=image_path, caption=image_path.name, mermaid=None)

    backend = MagicMock()
    backend.analyze.side_effect = record_thread

    result = IngestResult(
        markdown="\n".join(f"![](images/{p.name})" for p in images),
        images=images,
    )
    enrich_with_diagrams(result, backend=backend, concurrency=1)
    # All work serialized through a single worker thread.
    assert len(seen_threads) == 1


# --- gather + inject split -----------------------------------------


def test_gather_diagrams_returns_dict_does_not_mutate_markdown(tmp_path: Path) -> None:
    """gather_diagrams is a pure side-file producer: returns {basename: Diagram}
    and writes per-phash sidecars, but never touches markdown."""
    images = [tmp_path / f"img_{i}.png" for i in range(3)]
    for img in images:
        img.write_bytes(b"x")

    backend = MagicMock()
    backend.analyze.side_effect = lambda p, **_kw: Diagram(
        image_path=p, caption=f"caption-{p.name}", mermaid=None
    )

    by_basename = gather_diagrams(images, backend=backend, concurrency=2)

    assert set(by_basename.keys()) == {"img_0.png", "img_1.png", "img_2.png"}
    assert all(isinstance(d, Diagram) for d in by_basename.values())
    assert by_basename["img_0.png"].caption == "caption-img_0.png"


def test_gather_diagrams_no_images_returns_empty_dict() -> None:
    by_basename = gather_diagrams([], backend=MagicMock())
    assert by_basename == {}


def test_inject_diagrams_is_pure_transform() -> None:
    """inject_diagrams takes (markdown, dict) → markdown. No side files."""
    fake = Path("/fake/img.png")
    diagrams = {
        "img.png": Diagram(
            image_path=fake,
            caption="A test caption.",
            mermaid="flowchart TD\n  A --> B",
        )
    }
    md = "Before\n\n![](images/img.png)\n\nAfter\n"
    out = inject_diagrams(md, diagrams)
    assert "[A test caption.]" in out
    assert "```mermaid" in out
    assert "flowchart TD" in out


# --- cache_only mode ---------------------------------------------------------


class _RecordingBackend:
    """VisionBackend stub that fails the test if analyze() is ever called."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze(
        self, image_path: Path, *, phash: str | None = None, original_alt: str | None = None
    ) -> Diagram:
        self.calls += 1
        raise AssertionError("backend.analyze must not be called under cache_only")


def _seed_cache(cache_dir: Path, image_path: Path) -> None:
    """Write a vision-cache entry keyed by image_path's phash."""
    from pagespeak.services import _vision_cache as vcache
    from pagespeak.utils._phash import compute_phash

    cache_dir.mkdir(parents=True, exist_ok=True)
    phash = compute_phash(image_path)
    vcache.write(
        cache_dir / f"{phash}.json",
        diagram=Diagram(image_path=image_path, caption="cached caption", mermaid=None),
        backend="claude_code",
        model=None,
        phash=phash,
        source_paths=[image_path.name],
    )


def test_gather_cache_only_all_hits_makes_no_calls(tmp_path: Path) -> None:
    from pagespeak.services._diagrams import gather_diagrams

    img = _phashable_image(tmp_path / "img.png")
    cache_dir = tmp_path / ".vision-cache"
    _seed_cache(cache_dir, img)
    backend = _RecordingBackend()
    out = gather_diagrams(
        [img],
        backend=backend,
        backend_name="claude_code",
        cache_dir=cache_dir,
        cache_only=True,
    )
    assert backend.calls == 0
    assert out[img.name].caption == "cached caption"


def test_gather_cache_only_miss_skips_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging  # noqa: PLC0415

    from pagespeak.services._diagrams import gather_diagrams

    img = _phashable_image(tmp_path / "img.png")
    cache_dir = tmp_path / ".vision-cache"  # empty: every image misses
    backend = _RecordingBackend()
    with caplog.at_level(logging.WARNING):
        out = gather_diagrams(
            [img],
            backend=backend,
            backend_name="claude_code",
            cache_dir=cache_dir,
            cache_only=True,
        )
    assert backend.calls == 0
    # A miss yields NO handoff entry — inject must leave the original ref
    # (its authored alt) untouched, never ship a skip placeholder as content.
    assert img.name not in out
    assert "vision_cache_only_skipped" in caplog.text
    assert img.name in caplog.text


def test_gather_cache_only_miss_preserves_authored_alt(tmp_path: Path) -> None:
    """End-to-end gather+inject under cache-only: the uncached figure keeps its
    AUTHORED alt verbatim. Regression: skips used to inject
    `(no cached description; skipped under --vision-cache-only)` placeholders,
    destroying the authored alt corpus-wide."""
    from pagespeak.services._diagrams import gather_diagrams, inject_diagrams

    img = _phashable_image(tmp_path / "img.png")
    markdown = "Intro.\n\n![A labeled diagram of the water cycle.](images/img.png)\n"
    out = gather_diagrams(
        [img],
        backend=_RecordingBackend(),
        backend_name="claude_code",
        cache_dir=tmp_path / ".vision-cache",  # empty: miss
        cache_only=True,
    )
    result = inject_diagrams(markdown, out)
    assert "![A labeled diagram of the water cycle.](images/img.png)" in result
    assert "no cached description" not in result


def test_gather_then_inject_matches_enrich_output(tmp_path: Path) -> None:
    """Gather + inject pair must produce the same markdown as the
    legacy enrich_with_diagrams wrapper."""
    images = [tmp_path / "a.png", tmp_path / "b.png"]
    for img in images:
        img.write_bytes(b"x")

    backend = MagicMock()
    backend.analyze.side_effect = lambda p, **_kw: Diagram(
        image_path=p, caption=f"cap-{p.name}", mermaid=None
    )

    md = "![](images/a.png)\n\n![](images/b.png)\n"

    # Path 1: enrich (legacy wrapper)
    enrich_result = IngestResult(markdown=md, images=images)
    enrich_with_diagrams(enrich_result, backend=backend)

    # Path 2: gather then inject (new split)
    backend2 = MagicMock()
    backend2.analyze.side_effect = lambda p, **_kw: Diagram(
        image_path=p, caption=f"cap-{p.name}", mermaid=None
    )
    by_basename = gather_diagrams(images, backend=backend2)
    split_md = inject_diagrams(md, by_basename)

    assert enrich_result.markdown == split_md


# --- cross-client parity: retry=1 + preflight on Anthropic + OpenRouter ----


def test_anthropic_backend_constructs_pf_core_client_with_retry_1() -> None:
    """Contract test (pf-core retry adoption): when pagespeak builds its
    own `AnthropicClient` (caller didn't inject one), it must pass
    `retry=1` so pf-core retries transient SDK failures internally.
    Cross-client parity with the ClaudeCode adoption."""
    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}),
        patch("pf_core.clients.anthropic.AnthropicClient") as ctor,
    ):
        ctor.return_value = MagicMock()
        AnthropicVisionBackend(model="m")
    assert ctor.call_count == 1
    kwargs = ctor.call_args.kwargs
    assert kwargs.get("retry") == 1, (
        f"pagespeak must construct pf-core's AnthropicClient with retry=1; got kwargs={kwargs}"
    )


def test_openrouter_backend_constructs_pf_core_client_with_retry_1() -> None:
    """Contract test (pf-core retry adoption): when pagespeak builds its
    own `OpenRouterClient` (caller didn't inject one), it must pass
    `retry=1` so pf-core retries 429 / 5xx / timeout internally."""
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "k"}),
        patch("pf_core.clients.openrouter.OpenRouterClient") as ctor,
    ):
        ctor.return_value = MagicMock()
        OpenRouterVisionBackend()
    assert ctor.call_count == 1
    kwargs = ctor.call_args.kwargs
    assert kwargs.get("retry") == 1, (
        f"pagespeak must construct pf-core's OpenRouterClient with retry=1; got kwargs={kwargs}"
    )


def test_anthropic_preflight_check_delegates_to_client_preflight() -> None:
    """`AnthropicVisionBackend.preflight_check` is a 1-liner over pf-core's
    `AnthropicClient.preflight()`. Direct delegation — no
    pagespeak-side error transformation."""
    client = MagicMock()
    backend = AnthropicVisionBackend(client=client, model="m")
    backend.preflight_check()
    client.preflight.assert_called_once_with()


def test_openrouter_preflight_check_delegates_to_client_preflight() -> None:
    """`OpenRouterVisionBackend.preflight_check` is a 1-liner over pf-core's
    `OpenRouterClient.preflight()`. Direct delegation."""
    client = MagicMock()
    backend = OpenRouterVisionBackend(api_key="k", client=client, model="m")
    backend.preflight_check()
    client.preflight.assert_called_once_with()


def test_anthropic_preflight_check_propagates_pf_core_errors() -> None:
    """pf-core's `AnthropicClient.preflight()` raises `AnthropicError` (an
    `AppError`) with `ANTHROPIC_API_KEY` remediation on 401/403. Pagespeak's
    preflight_check propagates without wrapping — `gather_diagrams` aborts
    the batch before any per-image call fires."""
    from pf_core.exceptions import AppError

    client = MagicMock()
    client.preflight.side_effect = AppError(
        "Anthropic preflight failed: 401 unauthorized. Set ANTHROPIC_API_KEY.",
        context={"preflight": True},
    )
    backend = AnthropicVisionBackend(client=client, model="m")
    with pytest.raises(AppError) as exc_info:
        backend.preflight_check()
    assert "preflight failed" in str(exc_info.value)
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


def test_openrouter_preflight_check_propagates_pf_core_errors() -> None:
    """pf-core's `OpenRouterClient.preflight()` raises `OpenRouterError` on
    401/403 / 5xx / network. Pagespeak's preflight_check propagates."""
    from pf_core.exceptions import AppError

    client = MagicMock()
    client.preflight.side_effect = AppError(
        "OpenRouter preflight failed: 401 unauthorized. Set OPENROUTER_API_KEY.",
        context={"preflight": True},
    )
    backend = OpenRouterVisionBackend(api_key="k", client=client, model="m")
    with pytest.raises(AppError) as exc_info:
        backend.preflight_check()
    assert "preflight failed" in str(exc_info.value)
    assert "OPENROUTER_API_KEY" in str(exc_info.value)


# --- _claude_code_timeout_s (vision-side) ---


def test_vision_claude_code_timeout_returns_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S", raising=False)
    assert _claude_code_timeout_s() == CLAUDE_CODE_TIMEOUT_S_DEFAULT


def test_vision_claude_code_timeout_reads_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S", "60")
    assert _claude_code_timeout_s() == 60


def test_vision_claude_code_timeout_falls_back_on_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed env falls back via pf_core.resolve_int (warning covered there)."""
    monkeypatch.setenv("PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S", "not-an-int")
    assert _claude_code_timeout_s() == CLAUDE_CODE_TIMEOUT_S_DEFAULT


# --- alt_text_by_basename: source alt → vision prompt ---


def test_alt_text_by_basename_maps_alt_to_basename() -> None:
    from pagespeak.services._diagrams import alt_text_by_basename

    md = "![A pharynx illustration](images/abc.webp)\n\nbody\n\n![](images/def.png)"
    assert alt_text_by_basename(md) == {
        "abc.webp": "A pharynx illustration",
        "def.png": "",
    }


def test_alt_text_by_basename_strips_path_to_basename() -> None:
    from pagespeak.services._diagrams import alt_text_by_basename

    md = "![cap](../../images/deep/xyz.webp)"
    assert alt_text_by_basename(md) == {"xyz.webp": "cap"}


def test_alt_text_by_basename_first_occurrence_wins() -> None:
    from pagespeak.services._diagrams import alt_text_by_basename

    md = "![first](images/a.webp)\n![second](images/a.webp)"
    assert alt_text_by_basename(md)["a.webp"] == "first"


def test_alt_text_by_basename_no_images() -> None:
    from pagespeak.services._diagrams import alt_text_by_basename

    assert alt_text_by_basename("no images here") == {}


# --- alt-text-aware: backends forward original_alt into the prompt ---


def _text_block(content: list[dict]) -> str:
    return next(b["text"] for b in content if b.get("type") == "text")


def test_claude_code_backend_injects_original_alt(fake_image: Path) -> None:
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    backend.analyze(fake_image, original_alt="Distinctive source alt QQ77")
    prompt = client.chat.call_args.kwargs["messages"][0]["content"]
    assert "Distinctive source alt QQ77" in prompt


def test_claude_code_backend_no_alt_renders_none_provided(fake_image: Path) -> None:
    client = _mock_claude_client(json.dumps({"is_diagram": False, "caption": "x", "mermaid": None}))
    backend = ClaudeCodeVisionBackend(claude_bin="/fake/claude", client=client)
    backend.analyze(fake_image)
    prompt = client.chat.call_args.kwargs["messages"][0]["content"]
    assert "(none provided)" in prompt


def test_anthropic_backend_injects_original_alt(fake_image: Path) -> None:
    client = _mock_anthropic_client({"is_diagram": False, "caption": "x", "mermaid": None})
    backend = AnthropicVisionBackend(client=client, model="m")
    backend.analyze(fake_image, original_alt="Distinctive source alt QQ77")
    content = client.chat.call_args.kwargs["messages"][0]["content"]
    assert "Distinctive source alt QQ77" in _text_block(content)


def test_openrouter_backend_injects_original_alt(fake_image: Path) -> None:
    client = _mock_openrouter_client({"is_diagram": False, "caption": "x", "mermaid": None})
    backend = OpenRouterVisionBackend(api_key="k", client=client, model="m")
    backend.analyze(fake_image, original_alt="Distinctive source alt QQ77")
    content = client.chat.call_args.kwargs["messages"][0]["content"]
    assert "Distinctive source alt QQ77" in _text_block(content)


class _AltRecordingBackend:
    """Records the `original_alt` each image's analyze() received."""

    def __init__(self) -> None:
        self.seen: dict[str, str | None] = {}

    def analyze(
        self, image_path: Path, *, phash: str | None = None, original_alt: str | None = None
    ) -> Diagram:
        self.seen[image_path.name] = original_alt
        return Diagram(image_path=image_path, caption="c", mermaid=None)


def test_gather_passes_alt_to_backend_per_basename(tmp_path: Path) -> None:
    from pagespeak.services._diagrams import gather_diagrams

    img = _phashable_image(tmp_path / "pic.png")
    backend = _AltRecordingBackend()
    gather_diagrams(
        [img],
        backend=backend,
        backend_name="claude_code",
        alt_by_basename={"pic.png": "Source alt for pic ABC"},
    )
    assert backend.seen["pic.png"] == "Source alt for pic ABC"


def test_gather_defaults_alt_to_empty_when_unmapped(tmp_path: Path) -> None:
    from pagespeak.services._diagrams import gather_diagrams

    img = _phashable_image(tmp_path / "pic.png")
    backend = _AltRecordingBackend()
    gather_diagrams([img], backend=backend, backend_name="claude_code")
    assert backend.seen["pic.png"] == ""


def test_enrich_with_diagrams_feeds_source_alt(tmp_path: Path) -> None:
    """The legacy single-shot wrapper is alt-aware too: it pulls each
    figure's source alt from result.markdown and feeds it to the backend."""
    img = _phashable_image(tmp_path / "pic.png")
    backend = _AltRecordingBackend()
    result = IngestResult(markdown=f"![Library source alt DEF](images/{img.name})", images=[img])
    enrich_with_diagrams(result, backend=backend)
    assert backend.seen[img.name] == "Library source alt DEF"
