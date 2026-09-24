"""``python -m pagespeak.web`` → run the console under uvicorn."""

from __future__ import annotations

import uvicorn
from pf_core.log import get_logger

from pagespeak.web import create_app
from pagespeak.web._config import load_config
from pagespeak.web._security import bind_is_exposed

logger = get_logger(__name__)


def main() -> None:
    cfg = load_config()
    if bind_is_exposed(cfg.host):
        logger.warning(
            "web_console_exposed host=%s — the console has no authentication; anyone who "
            "can reach this port can upload documents, read conversions and start LLM runs. "
            "Bind to 127.0.0.1, or put it behind an authenticating proxy and list its "
            "hostname in PAGESPEAK_WEB_ALLOWED_HOSTS.",
            cfg.host,
        )
    uvicorn.run(create_app(), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
