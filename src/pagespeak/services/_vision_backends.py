"""Vision backends: the three `analyze(image) -> Diagram` LLM clients
(`Anthropic` / `ClaudeCode` / `OpenRouter`), the `VisionBackend` protocol, the
`build_backend` factory, and the response → `Diagram` parsing.

`_diagrams` re-exports every name here, so the public + test surface is
unchanged. Self-contained: imports only from pf-core / models / prompts (never
from `_diagrams`), so there is no import cycle.
"""

from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pf_core.log import get_logger
from pf_core.utils.env import resolve_int

from ..models._models import Diagram
from ..utils._prompts import DIAGRAM_PROMPT_VERSION, render_diagram_prompt
from ._vision_backend_openrouter import OpenRouterVisionBackend as OpenRouterVisionBackend
from ._vision_media import _media_type as _media_type
from ._vision_parse import _build_diagram

if TYPE_CHECKING:
    from pf_core.clients.claude_code import ClaudeCodeClient

logger = get_logger(__name__)

DEFAULT_VISION_MODEL = "claude-haiku-4-5-20251001"

# Per-image `claude --print` subprocess timeout (seconds). Operational
# tunable (env-configurable): bump via
# `PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S` if big diagrams or slow networks
# hit the default. Vision is per-image, so 120s is usually plenty —
# distinct from the whole-doc heading-normalize timeout
# (`PAGESPEAK_CLAUDE_CODE_TIMEOUT_S`, default 1800s).
CLAUDE_CODE_TIMEOUT_S_DEFAULT = 120
_CLAUDE_CODE_TIMEOUT_ENV_VAR = "PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S"


def _claude_code_timeout_s() -> int:
    """Read `PAGESPEAK_VISION_CLAUDE_CODE_TIMEOUT_S`; fall back to default."""
    n: int = resolve_int(None, _CLAUDE_CODE_TIMEOUT_ENV_VAR, default=CLAUDE_CODE_TIMEOUT_S_DEFAULT)
    return n


VisionBackendName = Literal["anthropic", "claude_code", "openrouter"]


# --- VisionBackend protocol ----------------------------------------------


@runtime_checkable
class VisionBackend(Protocol):
    """Anything that can take an image path and return a `Diagram`.

    optional ``phash`` kwarg lets the caller pass the
    already-computed perceptual hash so the tracking row can be linked
    back to a specific image without the backend re-hashing. Test mocks
    that don't care about tracking can omit it; the protocol's default
    of ``None`` keeps the existing call shape (``backend.analyze(img)``)
    fully backward-compatible.
    """

    def analyze(
        self,
        image_path: Path,
        *,
        phash: str | None = None,
        original_alt: str | None = None,
    ) -> Diagram: ...


# --- Anthropic backend (default) --------------------------


class AnthropicVisionBackend:
    """Calls Anthropic's messages API with a base64-encoded image payload.

    Costs API credits; the default backend is `claude_code` (free, local) —
    this class is for direct Anthropic-API use.

    Currently the transport layer is
    `pf_core.clients.anthropic.AnthropicClient` — same `(content, usage)`
    contract used by the `claude_code` and `openrouter` backends.
    Pagespeak retains the multimodal content-block construction; pf-core
    owns the SDK call + error mapping.

    Auth: `ANTHROPIC_API_KEY` env var by default, overridable via
    `api_key=` constructor kwarg. Callers can inject a pre-built pf-core
    `AnthropicClient` via `client=` for advanced use (custom timeouts,
    test mocks).
    """

    def __init__(
        self,
        *,
        client: object | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # model resolution delegated to `_agent_runtime.resolve_agent_config`.
        # YAML is the single source of truth; explicit `model=` still wins.
        # `DEFAULT_VISION_MODEL` retained as a final fallback only when no YAML
        # is present (matches `_HARDCODED_FALLBACKS["vision"]`).
        from .._agent_runtime import resolve_agent_config

        cfg = resolve_agent_config("vision", model_override=model, backend="anthropic")
        self._model = cfg["model"]
        if client is None:
            resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not resolved_key:
                raise RuntimeError(
                    "Anthropic backend requires an API key. Set "
                    "ANTHROPIC_API_KEY or pass `api_key=` to the constructor."
                )
            from pf_core.clients.anthropic import AnthropicClient as _AnthropicClient

            # `retry=1` (pf-core — cross-client parity with the
            # ClaudeCode adoption). Layers on top of
            # the Anthropic SDK's own internal retries; kicks in once SDK
            # retries are exhausted. Validation errors (no model
            # specified) are NOT retried by pf-core — deterministic input
            # bugs shouldn't burn API budget.
            client = _AnthropicClient(api_key=resolved_key, model=self._model, retry=1)
        self._client = client

    def preflight_check(self) -> None:
        """Smoke-test the Anthropic API auth + connectivity via pf-core's
        `AnthropicClient.preflight()`. Hits the cheap
        `models.list()` endpoint instead of burning a vision call. Raises
        `AnthropicError` (an `AppError`) with `ANTHROPIC_API_KEY`
        remediation on 401/403. Called by `gather_diagrams()` once per
        pass via duck-typed `hasattr` lookup — same dispatch as the
        ClaudeCode backend.
        """
        # `_client` is typed `object` (the `client=` ctor param accepts an
        # injected mock); the real client is an AnthropicClient and the caller
        # gates this call on `hasattr(..., "preflight_check")`. Duck-typed.
        self._client.preflight()  # type: ignore[attr-defined]

    def analyze(
        self,
        image_path: Path,
        *,
        phash: str | None = None,
        original_alt: str | None = None,
    ) -> Diagram:
        encoded = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        prompt = render_diagram_prompt(original_alt)

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _media_type(image_path),
                            "data": encoded,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        # route through `_agent_runtime.invoke_agent` so this
        # call captures a tracking row in `llm_runs` (when DB initialized)
        # and goes through the same model-resolution + record-writing
        # seam as heading_normalize. `client_override=self._client`
        # preserves test-injection of mock clients; `backend_override`
        # encodes this class's identity since classes pre-date the
        # env-var routing.
        from .._agent_runtime import invoke_agent

        content, _run_id = invoke_agent(
            "vision",
            messages=messages,
            prompt_version=DIAGRAM_PROMPT_VERSION,
            system_prompt_text=prompt,
            model_override=self._model,
            backend_override="anthropic",
            client_override=self._client,
            metadata={"image_basename": image_path.name, "image_phash": phash},
        )
        return _build_diagram(image_path, content)


# --- Claude Code backend ------------------------------------------


class ClaudeCodeVisionBackend:
    """Routes vision calls through the local `claude --print` CLI.

    Uses the active Claude Code session — no API cost. Currently the
    transport layer is `pf_core.clients.claude_code.ClaudeCodeClient`:
    pagespeak retains the vision-specific concerns (prompt construction
    pointing at an absolute image path, preflight check, RuntimeError
    formatting), pf-core owns the subprocess machinery and the
    transient-retry behavior.

    Model resolution mirrors `AnthropicVisionBackend`: explicit `model=`
    arg > `config/model_router.yaml` (`agents.vision.backends.claude_code.model`)
    > hardcoded `DEFAULT_VISION_MODEL` (haiku). The resolved model is
    passed to `claude --print --model …` on every call. **Never falls
    through to None.** This is deliberate cost protection: without
    `--model`, `claude --print` uses the user's interactive session
    model — for someone on Claude Max, that's Sonnet/Opus, and a
    1000-image vision pass can quietly burn a day's Max usage. Forcing
    Haiku by default keeps batch vision cheap; callers who genuinely
    want Opus pass it explicitly.

    Trade-offs vs `AnthropicVisionBackend`:
        - $0 per call (uses your Claude Code session/subscription)
        - 1-3s wall-clock per image vs ~500ms direct API
        - Requires the `claude` binary on PATH
    """

    def __init__(
        self,
        *,
        claude_bin: str | None = None,
        model: str | None = None,
        client: ClaudeCodeClient | None = None,
    ) -> None:
        # model resolution delegated to `_agent_runtime.resolve_agent_config`.
        # YAML wins over hardcoded fallback; explicit `model=` still wins over both.
        from .._agent_runtime import resolve_agent_config

        cfg = resolve_agent_config("vision", model_override=model, backend="claude_code")
        self._model = cfg["model"]
        # Caller can inject a pre-built ClaudeCodeClient (test mocks rely on
        # this); otherwise we build one with pagespeak's 120s vision-call
        # timeout. pf-core's ClaudeCodeClient resolves the binary via
        # `shutil.which` at chat()-time, so we surface a missing-binary error
        # eagerly here to keep the error message intact.
        binary_arg = claude_bin or "binary-not-resolved-yet"
        if client is None:
            from pf_core.clients.claude_code import ClaudeCodeClient as _ClaudeCodeClient

            resolved_bin = claude_bin or shutil.which("claude")
            if not resolved_bin:
                raise RuntimeError(
                    "Claude Code CLI not found on PATH. Install it from "
                    "https://claude.com/claude-code or pass an explicit `claude_bin`."
                )
            binary_arg = resolved_bin
            # Some pf-core versions don't accept `model=` in __init__; pass
            # it per-call via chat(model=...) instead (the per-call arg wins
            # over any constructor default anyway). `retry=1` means up to 2
            # attempts per chat() — pf-core retries internally on timeout /
            # non-zero exit, so analyze() needs no retry loop of its own.
            client = _ClaudeCodeClient(
                timeout=_claude_code_timeout_s(),
                binary=resolved_bin,
                retry=1,
            )
        else:
            # When the caller injects a client (tests, advanced consumers), we
            # don't have a binary path to log — fall back to whatever the
            # caller passed for `claude_bin` (or the injected client's
            # attribute if present).
            binary_arg = claude_bin or str(getattr(client, "binary", "claude"))
        self._client = client
        self._bin = binary_arg
        # One-line visibility on init so end-to-end runs surface the resolved
        # model without the user having to enable DEBUG logging. Critical for
        # post-mortem when a vision pass burns through the wrong quota.
        logger.info(
            "claude_code_vision_backend_initialized model=%s bin=%s",
            self._model,
            self._bin,
        )

    def _run_once(
        self, prompt: str, image_name: str, phash: str | None = None, *, system_text: str
    ) -> str:
        """Single chat invocation routed through `_agent_runtime.invoke_agent`.

        Going through the invoke_agent seam captures a `llm_runs`
        tracking row (when DB initialized) and shares the same model-
        resolution + record-writing as heading_normalize.

        The client was constructed with `retry=1`, so pf-core retries
        transient failures internally before raising. Returns the raw
        response content; raises RuntimeError if pf-core's retry-loop
        also failed (the formatted RuntimeError preserves the
        diagnostic contract: model + stdout + stderr_head).
        """
        from pf_core.exceptions import AppError

        from .._agent_runtime import invoke_agent

        try:
            content, _run_id = invoke_agent(
                "vision",
                messages=[{"role": "user", "content": prompt}],
                prompt_version=DIAGRAM_PROMPT_VERSION,
                system_prompt_text=system_text,
                model_override=self._model,
                backend_override="claude_code",
                client_override=self._client,
                metadata={"image_basename": image_name, "image_phash": phash},
            )
            assert isinstance(content, str)  # pf-core's chat() contract
            return content
        except AppError as e:
            # pf-core's ClaudeCodeError carries stderr_head + returncode in
            # `e.context`. Surface them inline so the visibility
            # contract holds (failure message names model + stdout + stderr).
            ctx = getattr(e, "context", {}) or {}
            stderr_head = ctx.get("stderr_head", "")
            returncode = ctx.get("returncode", "?")
            raise RuntimeError(
                f"claude --print exited {returncode} on "
                f"{image_name} (model={self._model}); "
                f"stdout={str(e)[:500]!r} stderr={stderr_head[:500]!r}"
            ) from e

    def preflight_check(self) -> None:
        """Smoke-test the local Claude Code session via pf-core's
        `ClaudeCodeClient.preflight()`. Raises `ClaudeCodeError` (an
        `AppError`) with an actionable `<bin> /login` remediation
        message if the call fails. Called by `gather_diagrams()` once
        per pass via duck-typed hasattr lookup.
        """
        self._client.preflight()

    def analyze(
        self,
        image_path: Path,
        *,
        phash: str | None = None,
        original_alt: str | None = None,
    ) -> Diagram:
        rendered = render_diagram_prompt(original_alt)
        prompt = f"Read the image at {image_path.resolve()}.\n\n{rendered}"
        # pf-core's ClaudeCodeClient (constructed with retry=1) handles the
        # transient-session-blip retry internally; _run_once sees only the
        # final failure if both attempts fail.
        content = self._run_once(prompt, image_path.name, phash=phash, system_text=rendered)
        return _build_diagram(image_path, content)


# --- Backend factory ------------------------------------------------------


def build_backend(
    name: VisionBackendName,
    *,
    model: str | None = None,
) -> VisionBackend:
    """Construct a vision backend by name (`claude_code` / `anthropic` /
    `openrouter`). `claude_code` routes through the local `claude --print` CLI
    for $0 calls."""
    if name == "anthropic":
        return AnthropicVisionBackend(model=model)
    if name == "claude_code":
        return ClaudeCodeVisionBackend(model=model)
    if name == "openrouter":
        return OpenRouterVisionBackend(model=model)
    raise ValueError(f"Unknown vision_backend: {name!r}")
