# Operations

Runtime environments where pagespeak behaves differently than on a normal developer machine, and what to do about it.

---

## Table of Contents

- [Sandboxed shells block `ProcessPoolExecutor`](#sandboxed-shells-block-processpoolexecutor)
- [Re-validating a Phase-3 change](#re-validating-a-phase-3-change)
- [Adding to this page](#adding-to-this-page)

---

## Sandboxed shells block `ProcessPoolExecutor`

**Symptom.** `pagespeak convert` or `pagespeak ingest --workers N` fails during PDF work with a traceback through `concurrent/futures/process.py` and `PermissionError`, often mentioning `os.sysconf` or `_check_system_limits`:

```text
PermissionError: [Errno 1] Operation not permitted
  File ".../concurrent/futures/process.py", line 613, in _check_system_limits
    nsems_max = os.sysconf("SC_SEM_NSEMS_MAX")
```

The traceback may point into Marker or `concurrent.futures`, not pagespeak directly. pagespeak re-raises with a short message that points here.

**Cause.** On some macOS setups, sandboxes deny `os.sysconf("SC_SEM_NSEMS_MAX")`. Python's `ProcessPoolExecutor` calls that during construction. Marker uses a process pool internally during PDF conversion; the phased pipeline uses `ProcessPoolExecutor` in `orchestrators._chunk.chunk()` to fan out chunk workers. Either path can fail the same way.

**Do:**

| Environment | Workaround |
|---|---|
| Cursor agent / tool sandbox | Run the command with full permissions (e.g. `required_permissions=["all"]` for the tool invocation). |
| macOS GUI / other sandboxes | Run from an unrestricted Terminal, or adjust sandbox / Full Disk Access so `sysconf` is allowed. |
| CI (typical Linux) | Usually unaffected — limits are readable without special privileges. |
| Custom containers | Ensure the runtime allows `ProcessPoolExecutor` to start (no seccomp blocking the relevant syscalls). |

**Do not** expect pagespeak to auto-fallback to a serial pool: that would silently turn multi-hour jobs into much slower runs without a clear signal.

## Re-validating a Phase-3 change

After changing a Phase-3 stage (cleanup, normalize, split, …) you usually want to re-run the pipeline against already-converted output dirs and confirm the change did what you intended. Do it in this order — skipping the last step is the canonical way to ship a regression.

1. **Read the original flags.** For each output dir, read `.pagespeak-run.json` → `resolved_flags`. Note `split_sections`, `nested_split`, `preset`, `normalize_headings*`, etc.
2. **Re-run with the SAME flags.** `pagespeak convert <dir> --rerun-from <stage>` **plus** the original output-shaping flags (`--split-sections --nested-split`, the preset, …). `--rerun-from` deletes downstream structural outputs (`sections/`, `INDEX.md`); omitting the flags that produce them leaves them deleted. See [docs/caching.md](caching.md) § "Destructive".
3. **Read the output by eye.** Open the rendered `<stem>.md` and a `sections/` sample for several representative docs and *read them*. A zero diff-count or a passing token-grep is a gate, not a verdict — the prior output may already be wrong. Pin the read as the definition of done.

**Symptom this prevents.** `--rerun-from normalize` run without `--split-sections` once deleted `sections/` across an entire batch of converted documents; a separate re-validation pass then declared the output "fine" on a 0-diff while the heading hierarchy had been broken upstream the whole time. Both are detectable only by steps 1–3 above.

## Adding to this page

Document post-install, environment-specific gotchas here — not API details that belong next to the code. Keep entries actionable (symptom, cause, fix).
