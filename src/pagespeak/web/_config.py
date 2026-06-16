"""Web-console runtime config, resolved from env vars.

All vars are namespaced ``PAGESPEAK_*`` (pagespeak's house style) to stay
collision-proof against bare ``PORT`` in a shared shell. Port default 8810
is verified clear of the sibling projects' .env ports (see the design spec).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebConfig:
    """Resolved web-console settings."""

    conversions_dir: Path
    host: str
    port: int
    concurrency: int

    @property
    def in_dir(self) -> Path:
        return self.conversions_dir / "in"

    @property
    def out_dir(self) -> Path:
        return self.conversions_dir / "out"

    @property
    def delivery_dir(self) -> Path:
        return self.conversions_dir / "delivery"


def load_config() -> WebConfig:
    """Resolve :class:`WebConfig` from ``PAGESPEAK_*`` env vars."""
    conv = os.environ.get("PAGESPEAK_CONVERSIONS_DIR")
    conversions_dir = Path(conv) if conv else (Path.cwd() / "conversions")
    return WebConfig(
        conversions_dir=conversions_dir,
        host=os.environ.get("PAGESPEAK_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("PAGESPEAK_WEB_PORT", "8810")),
        concurrency=int(os.environ.get("PAGESPEAK_WEB_CONCURRENCY", "1")),
    )
