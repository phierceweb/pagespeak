from __future__ import annotations

from pagespeak.web._command import build_command
from pagespeak.web._jobs import ConversionInputs, ConversionOptions


def test_full_run_uses_source_no_phase_flags():
    inp = ConversionInputs(
        out_dir="/c/out/doc",
        source_path="/c/in/Doc.pdf",
        options=ConversionOptions(diagrams=False, cleanup="basic"),
    )
    cmd = build_command(inp, pagespeak_bin="/venv/bin/pagespeak")
    assert cmd[:3] == ["/venv/bin/pagespeak", "convert", "/c/in/Doc.pdf"]
    assert "-o" in cmd and "/c/out/doc" in cmd
    assert "--from" not in cmd
    assert "--no-diagrams" in cmd
    assert "--cleanup" in cmd and "basic" in cmd


def test_ingest_only_uses_source_and_stop_after():
    inp = ConversionInputs(
        out_dir="/c/out/doc", source_path="/c/in/Doc.pdf", start="ingest", stop_after="ingest"
    )
    cmd = build_command(inp, pagespeak_bin="ps")
    assert cmd[2] == "/c/in/Doc.pdf"
    assert "--stop-after" in cmd and "ingest" in cmd


def test_midslice_uses_out_dir_and_from():
    inp = ConversionInputs(
        out_dir="/c/out/doc", source_path=None, start="cleanup", stop_after="vision"
    )
    cmd = build_command(inp, pagespeak_bin="ps")
    assert cmd[2] == "/c/out/doc"
    assert "--from" in cmd and "cleanup" in cmd
    assert "--stop-after" in cmd and "vision" in cmd


def test_vision_options_threaded():
    inp = ConversionInputs(
        out_dir="/c/out/doc",
        source_path="/c/in/Doc.pdf",
        options=ConversionOptions(
            vision_backend="claude_code",
            vision_cache_only=True,
            split_sections=True,
            nested_split=True,
            normalize_headings=True,
            normalize_headings_mode="llm_full",
            normalize_headings_backend="openrouter",
            workers=2,
        ),
    )
    cmd = build_command(inp, pagespeak_bin="ps")
    assert "--vision-backend" in cmd and "claude_code" in cmd
    assert "--vision-cache-only" in cmd
    assert "--split-sections" in cmd and "--nested-split" in cmd
    assert "--normalize-headings" in cmd
    assert "--normalize-headings-mode" in cmd and "llm_full" in cmd
    assert "--normalize-headings-backend" in cmd and "openrouter" in cmd
    assert "--workers" in cmd and "2" in cmd
