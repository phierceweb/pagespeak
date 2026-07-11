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

# Per-image `claude --print` timeout — distinct from the whole-doc
# heading-normalize timeout (`PAGESPEAK_CLAUDE_CODE_TIMEOUT_S`, 1800s).
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

    The optional ``phash`` kwarg carries the already-computed perceptual hash
    for the tracking row; its ``None`` default keeps ``analyze(img)`` valid.
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

    Costs API credits; the default backend is `claude_code` (free, local).
    Transport is pf-core's `AnthropicClient` (pagespeak builds the multimodal
    content blocks). Auth: `ANTHROPIC_API_KEY` env var or `api_key=`; a
    pre-built client can be injected via `client=` (timeouts, test mocks).
    """

    def __init__(
        self,
        *,
        client: object | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # Model resolution: explicit `model=` > YAML > DEFAULT_VISION_MODEL.
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

            # retry=1: one pf-core retry after the SDK's own retries are exhausted.
            client = _AnthropicClient(api_key=resolved_key, model=self._model, retry=1)
        self._client = client

    def preflight_check(self) -> None:
        """Smoke-test auth via the cheap `models.list()` (no vision call burned).
        Raises `AnthropicError` with `ANTHROPIC_API_KEY` remediation on 401/403.
        """
        # `_client` is typed `object` (injectable mock); duck-typed real call.
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
        # invoke_agent captures the llm_runs tracking row; client_override
        # preserves test-injected mocks.
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

    $0 per call (active Claude Code session), ~1-3s per image vs ~500ms direct
    API, needs the `claude` binary on PATH. Transport is pf-core's
    `ClaudeCodeClient`, which runs the subprocess with `--safe-mode` by default
    so the cwd project's CLAUDE.md/skills can't hijack a caption.

    Model resolution: explicit `model=` > YAML > `DEFAULT_VISION_MODEL`
    (haiku); the resolved model is always passed as `--model` — **never None**.
    Cost protection: without `--model`, `claude --print` uses the interactive
    session model (Sonnet/Opus on Max), and a 1000-image pass would quietly
    burn a day's quota.
    """

    def __init__(
        self,
        *,
        claude_bin: str | None = None,
        model: str | None = None,
        client: ClaudeCodeClient | None = None,
    ) -> None:
        # Model resolution: explicit `model=` > YAML > hardcoded fallback.
        from .._agent_runtime import resolve_agent_config

        cfg = resolve_agent_config("vision", model_override=model, backend="claude_code")
        self._model = cfg["model"]
        # Resolve the binary eagerly so a missing install fails with a clear
        # message here, not deep inside chat().
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
            # Model goes per-call via chat(model=...) (older pf-core lacks the
            # ctor kwarg); retry=1 = pf-core retries transients internally.
            client = _ClaudeCodeClient(
                timeout=_claude_code_timeout_s(),
                binary=resolved_bin,
                retry=1,
            )
        else:
            # Injected client (tests): no binary path of our own to log.
            binary_arg = claude_bin or str(getattr(client, "binary", "claude"))
        self._client = client
        self._bin = binary_arg
        # INFO-log the resolved model so a wrong-quota vision run is diagnosable.
        logger.info(
            "claude_code_vision_backend_initialized model=%s bin=%s",
            self._model,
            self._bin,
        )

    def _run_once(
        self, prompt: str, image_name: str, phash: str | None = None, *, system_text: str
    ) -> str:
        """One chat invocation via `invoke_agent` (captures the llm_runs row).

        pf-core retries transients internally (`retry=1`); raises RuntimeError
        naming model + stdout + stderr_head when both attempts fail.
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
            # Surface pf-core's stderr_head + returncode inline in the message.
            ctx = getattr(e, "context", {}) or {}
            stderr_head = ctx.get("stderr_head", "")
            returncode = ctx.get("returncode", "?")
            raise RuntimeError(
                f"claude --print exited {returncode} on "
                f"{image_name} (model={self._model}); "
                f"stdout={str(e)[:500]!r} stderr={stderr_head[:500]!r}"
            ) from e

    def preflight_check(self) -> None:
        """Smoke-test the local session; raises `ClaudeCodeError` with a
        `<bin> /login` remediation on failure."""
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
