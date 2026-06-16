"""One-call DB initialization for the web console.

``pagespeak._db.init_db()`` creates the entire pf_core schema — tracking,
jobs, budget, and cache tables — because they all share one ``MetaData``.
The console needs jobs (queue) + tracking (LLM hits) + budget/cache (the
mounted admin pages), so this is the single init the app calls at startup.
"""

from __future__ import annotations

from pagespeak._db import init_db


def init_web_db() -> None:
    """Create all pf_core tables the console reads/writes. Idempotent."""
    init_db()
