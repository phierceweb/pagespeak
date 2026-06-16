"""``python -m pagespeak.web`` → run the console under uvicorn."""

from __future__ import annotations

import uvicorn

from pagespeak.web import create_app
from pagespeak.web._config import load_config


def main() -> None:
    cfg = load_config()
    uvicorn.run(create_app(), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
