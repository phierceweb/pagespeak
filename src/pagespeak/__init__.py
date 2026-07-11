"""pagespeak — convert documents to LLM-friendly markdown with diagram extraction."""

from __future__ import annotations

import os as _os

from pf_core.log import setup_logging as _setup_logging

# Configure pf-core's structlog bridge BEFORE the sub-imports: their get_logger
# calls lazy-init setup_logging (first caller wins), so bind the `pagespeak`
# root here. Library users may call setup_logging() before importing.
_setup_logging(
    level=_os.environ.get("PAGESPEAK_LOG_LEVEL"),
    app_logger_name="pagespeak",
)

from .backends._pdf_dispatch import PdfBackendName  # noqa: E402
from .models._models import Diagram, IngestResult  # noqa: E402
from .models._pipeline import ChunkState, Manifest, VisionState  # noqa: E402
from .orchestrators._chunk import chunk  # noqa: E402
from .orchestrators._dispatch import to_markdown  # noqa: E402
from .orchestrators._ingest import ingest  # noqa: E402
from .services._cleanup import CleanupLevel, CrossRefs  # noqa: E402
from .services._diagrams import (  # noqa: E402
    VisionBackendName,
    gather_diagrams,
    inject_diagrams,
)
from .services._heading_normalize import (  # noqa: E402
    NormalizeData,
    NormalizeMode,
    apply_normalization,
    gather_normalize_levels,
)
from .services._rerun import RERUN_STAGES  # noqa: E402

__version__ = "0.5.0"
__all__ = [
    "ChunkState",
    "CleanupLevel",
    "CrossRefs",
    "Diagram",
    "IngestResult",
    "Manifest",
    "NormalizeData",
    "NormalizeMode",
    "PdfBackendName",
    "RERUN_STAGES",
    "VisionBackendName",
    "VisionState",
    "apply_normalization",
    "chunk",
    "gather_diagrams",
    "gather_normalize_levels",
    "inject_diagrams",
    "ingest",
    "to_markdown",
]
