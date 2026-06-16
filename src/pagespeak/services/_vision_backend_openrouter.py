"""OpenRouter vision backend — `analyze(image) -> Diagram` via OpenRouter's
chat-completions endpoint.

`_vision_backends` re-imports `OpenRouterVisionBackend` for the `build_backend`
factory + the public re-export surface, so the import path is unchanged.
Self-contained: imports the shared media-type helper from `_vision_media`,
never from `_vision_backends` (no import cycle).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models._models import Diagram
from ..utils._prompts import DIAGRAM_PROMPT_VERSION, render_diagram_prompt
from ._vision_media import _media_type
from ._vision_parse import _build_diagram

if TYPE_CHECKING:
    from pf_core.clients.openrouter import OpenRouterClient


class OpenRouterVisionBackend:
    """Calls OpenRouter's chat-completions endpoint.

    Useful when a consumer already standardizes on OpenRouter for unified
    billing across providers (Anthropic, OpenAI, Google, etc.) and wants
    pagespeak's vision pass to ride the same auth + invoicing lane.

    Currently the transport layer is
    `pf_core.clients.openrouter.OpenRouterClient`. Pagespeak retains the
    multimodal content-block construction; pf-core owns the HTTP call.

    Trade-offs:
        - ~5-10% markup on credits vs direct Anthropic API
        - ~100ms extra latency per call (proxy hop)
        - No Anthropic prompt-caching exposure
        - Extra failure point
        - 3-5× faster than the `claude_code` subprocess backend, and
          supports model selection (`anthropic/...`, `google/gemini-...`,
          `meta-llama/...`)

    Auth: `OPENROUTER_API_KEY` env var by default, overridable via
    `api_key=` constructor kwarg.
    """

    # Cost-protection fallback when YAML is absent / unreadable. Same
    # `anthropic/claude-haiku-4.5` slug as before, to preserve the
    # historical default; `config/model_router.yaml` sets the real model
    # (`google/gemini-2.5-flash` for vision/openrouter).
    DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        client: OpenRouterClient | None = None,
    ) -> None:
        # model resolution — explicit `model=` > YAML
        # `agents.vision.backends.openrouter.model` > class `DEFAULT_MODEL`.
        # Bypasses `_agent_runtime._HARDCODED_FALLBACKS` for the no-YAML edge
        # case: its Anthropic-native slug would 404 against OpenRouter, so this
        # class's OpenRouter-shaped `DEFAULT_MODEL` is used instead.
        if model is not None:
            self._model = model
        else:
            from .._agent_runtime import _load_yaml_config

            yaml_data = _load_yaml_config()
            vision_block = (yaml_data.get("agents") or {}).get("vision") or {}
            backends_block = vision_block.get("backends") or {}
            openrouter_cfg = backends_block.get("openrouter") or {}
            self._model = openrouter_cfg.get("model") or self.DEFAULT_MODEL
        if client is None:
            resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
            if not resolved_key:
                raise RuntimeError(
                    "OpenRouter backend requires an API key. Set "
                    "OPENROUTER_API_KEY or pass `api_key=` to the constructor."
                )
            from pf_core.clients.openrouter import OpenRouterClient as _OpenRouterClient

            # `retry=1` (pf-core — cross-client parity). pf-core
            # retries `httpx.TimeoutException`, status 429 (rate limit),
            # and status 5xx; does NOT retry other 4xx (caller errors
            # that won't get better on retry — preserves API budget).
            kwargs: dict[str, Any] = {"api_key": resolved_key, "retry": 1}
            if base_url is not None:
                kwargs["base_url"] = base_url
            client = _OpenRouterClient(**kwargs)
        self._client = client

    def preflight_check(self) -> None:
        """Smoke-test OpenRouter auth + connectivity via pf-core's
        `OpenRouterClient.preflight()`. Hits the cheap
        `GET /models` endpoint instead of burning a vision call. Raises
        `OpenRouterError` (an `AppError`) with `OPENROUTER_API_KEY`
        remediation on 401/403, generic preflight-failed on 5xx /
        network / timeout. Called by `gather_diagrams()` once per pass
        via duck-typed `hasattr` lookup.
        """
        self._client.preflight()

    def analyze(
        self,
        image_path: Path,
        *,
        phash: str | None = None,
        original_alt: str | None = None,
    ) -> Diagram:
        encoded = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        media = _media_type(image_path)
        prompt = render_diagram_prompt(original_alt)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{encoded}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        # route through `_agent_runtime.invoke_agent` for
        # tracking. See AnthropicVisionBackend.analyze for rationale.
        from .._agent_runtime import invoke_agent

        content, _run_id = invoke_agent(
            "vision",
            messages=messages,
            prompt_version=DIAGRAM_PROMPT_VERSION,
            system_prompt_text=prompt,
            model_override=self._model,
            backend_override="openrouter",
            client_override=self._client,
            metadata={"image_basename": image_path.name, "image_phash": phash},
        )
        return _build_diagram(image_path, content)
