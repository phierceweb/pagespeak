"""The sequencer — the "some other process" that runs phases in order.

It owns ZERO pipeline logic. Its only job: given an ordered list of
`Phase` objects, decide which contiguous slice to run and run it.

Slice selection:
- `start` given      → run from there (single-phase / `from`).
- else `rerun_from`   → run from there regardless of freshness (the
                        caller invalidated that stage's caches first).
- else (resume)       → skip the leading run of phases whose output is
                        already fresh; run from the first stale one.
- `stop_after` given  → stop after that phase (else run to the end).

Single phase == `start == stop_after`. A run can now start late AND
stop early — the half that was missing from the monolith.
"""

from __future__ import annotations

from ._phase import Phase


class UnknownStageError(ValueError):
    """A `start` / `stop_after` / `rerun_from` name not in the phase list."""


def _index(names: list[str], stage: str | None, *, label: str) -> int | None:
    if stage is None:
        return None
    try:
        return names.index(stage)
    except ValueError:
        raise UnknownStageError(
            f"unknown {label} stage: {stage!r}. Valid: {tuple(names)}"
        ) from None


def run_pipeline(
    phases: list[Phase],
    *,
    ctx: object,
    start: str | None = None,
    stop_after: str | None = None,
    rerun_from: str | None = None,
) -> list[str]:
    """Run the selected slice of `phases` in order. Returns the names of
    the phases actually run, in order.

    Args:
        phases: Ordered pipeline phases.
        ctx: Opaque pipeline context handed to each phase.
        start: Force the run to begin at this phase (single-phase / from).
        stop_after: Halt after this phase (default: run to the end).
        rerun_from: Begin here regardless of freshness. Caller is
            responsible for having invalidated this stage's caches.

    Raises:
        UnknownStageError: a stage name is not in `phases`.
        ValueError: `stop_after` resolves before the start phase.
    """
    names = [p.name for p in phases]
    start_i = _index(names, start, label="start")
    stop_i = _index(names, stop_after, label="stop_after")
    rerun_i = _index(names, rerun_from, label="rerun_from")

    if start_i is not None:
        begin = start_i
    elif rerun_i is not None:
        begin = rerun_i
    else:
        # Resume: skip the leading run of fresh phases.
        begin = next(
            (i for i, p in enumerate(phases) if not p.is_fresh(ctx)),
            len(phases),
        )

    if begin >= len(phases):
        return []  # nothing stale / nothing to do

    end = stop_i if stop_i is not None else len(phases) - 1
    if end < begin:
        raise ValueError(
            f"stop_after={stop_after!r} resolves before start {names[begin]!r} — empty run"
        )

    ran: list[str] = []
    for phase in phases[begin : end + 1]:
        phase.run(ctx)
        ran.append(phase.name)
    return ran


__all__ = ["UnknownStageError", "run_pipeline"]
