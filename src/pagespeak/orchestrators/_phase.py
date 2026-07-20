"""The Phase contract — one pipeline stage as an independently runnable
unit whose on-disk checkpoint is its sole interface to its neighbours.

A `Phase` reads its input checkpoint, does its work, and writes its
output checkpoint. Phases never hand an in-memory markdown string to
each other; the checkpoint file IS the interface. This is what makes a
single phase runnable in isolation: give it a valid input checkpoint,
run it, read its output checkpoint.

The concrete pipeline phases live one-per-stage and are sequenced by
`pf_core.pipeline.sequencer.run_pipeline`. pf-core's `Phase` protocol is
just `name` + `run`; this one adds `is_fresh` — pagespeak's resume
convention, consumed by the `skip_fresh` closure at the dispatch call
site.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Phase(Protocol):
    """One pipeline stage.

    `name` must match the stage name in `services._rerun.RERUN_STAGES`
    so cache invalidation and the sequencer agree on ordering.
    """

    name: str

    def is_fresh(self, ctx: object) -> bool:
        """True when this phase's output checkpoint is already valid for
        `ctx` (resume can skip it). False forces a run."""
        ...

    def run(self, ctx: object) -> None:
        """Load the input checkpoint, do the work, write the output
        checkpoint. Idempotent given the same input checkpoint + ctx."""
        ...


__all__ = ["Phase"]
