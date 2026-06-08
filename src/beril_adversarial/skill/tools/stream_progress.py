#!/usr/bin/env python3
"""Parse `claude -p --output-format stream-json` output.

Two purposes, both load-bearing:

1. **Programmatic Write-tool verification.** Detects the silent-failure
   case where claude produces a chat-response review without invoking
   Write. Exit code 2 lets the shell script's retry helper kick in.

2. **End-of-run cost summary.** Tokens and estimated USD cost printed
   to stderr after the stream completes.

What was here and got cut: per-tool-call breakdown by type (cosmetic;
not load-bearing), parse-error printing during run (counter retained),
detailed progress lines (Claude Code batches bash output so they
weren't visible in real time anyway).

Stdin: stream-json events from claude.
Stdout: by default, passthrough of the raw events (consumed by
  `> /dev/null` in the legacy pipeline). With --reemit-text, the
  assistant's streamed TEXT is re-emitted instead (human-readable
  live progress — used by the presentation/paper review path, which
  shows the reasoning as it flows rather than going silent-until-done).
Stderr: end-of-run summary.

Multi-file reviews (Cycle 3): --expected-write-path may be given
MULTIPLE times. With one path the historical semantics hold (that one
path must be written). With several, EACH must be written (the
presentation/paper reviewer writes both .md and .json). With none,
Write verification is skipped entirely (exit 0 regardless) — the call
is then used purely for the cost/usage capture + text re-emit.

Exit codes:
  0 — every expected Write target was invoked (or none required)
  2 — an expected Write was NEVER invoked (silent-failure — retryable)
  3 — an expected target was not among the written paths
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


# Per-million-token rates (USD). Rough estimates for cost orientation.
_MODEL_RATES = {
    "sonnet": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_create": 3.75},
    "opus":   {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_create": 18.75},
    "haiku":  {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_create": 1.00},
}


def _classify_model(model: str) -> str | None:
    if not model:
        return None
    m = model.lower()
    for family in ("opus", "haiku", "sonnet"):
        if family in m:
            return family
    return None


def _estimate_cost(usage: dict, model: str | None) -> float | None:
    family = _classify_model(model or "")
    if family is None:
        return None
    r = _MODEL_RATES[family]
    return (
        usage.get("input_tokens", 0) * r["input"]
        + usage.get("output_tokens", 0) * r["output"]
        + usage.get("cache_read_input_tokens", 0) * r["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) * r["cache_create"]
    ) / 1_000_000


def _path_was_written(expected_write_path: str, write_paths: list[str]) -> bool:
    """True iff `expected_write_path` matches one of the written paths.
    Match order: resolved-absolute equality, then absolute equality,
    then basename equality (the historical fallback for relative vs
    absolute path shapes)."""
    try:
        expected_abs = Path(expected_write_path).resolve()
    except (OSError, RuntimeError):
        expected_abs = None
    for p in write_paths:
        if expected_abs is not None:
            try:
                if Path(p).resolve() == expected_abs:
                    return True
            except (OSError, RuntimeError):
                pass
        try:
            p_path = Path(p)
            e_path = Path(expected_write_path)
            if p_path.is_absolute() and e_path.is_absolute():
                if p_path == e_path:
                    return True
            elif p_path.name == e_path.name:
                return True
        except (OSError, ValueError):
            continue
    return False


def _write_metadata_json(metadata_path: Path, metadata: dict) -> bool:
    """Write a per-call metadata JSON sidecar.

    Used by the shell-level aggregator to compute cumulative cost
    across multiple claude calls in the review pipeline (main +
    critic + fix + re-critic). The aggregator at end of pipeline
    sums these and writes ONE cumulative Run Metadata section to
    the review file.

    Returns True on success.
    """
    try:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return True
    except OSError:
        return False


def _emit_assistant_text(event: dict) -> None:
    """Re-emit the assistant's text content from a stream event to
    stdout, so the user watches the review reason in real time (the
    bare `claude -p` behavior we must not regress). Handles the
    streaming delta shape (content_block_delta / text_delta) and the
    batched assistant-message shape."""
    etype = event.get("type")
    if etype == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") in (None, "text_delta") and delta.get("text"):
            sys.stdout.write(delta["text"])
            sys.stdout.flush()
    elif etype == "assistant":
        for cb in (event.get("message", {}) or {}).get("content", []) or []:
            if isinstance(cb, dict) and cb.get("type") == "text" and cb.get("text"):
                sys.stdout.write(cb["text"])
                sys.stdout.flush()


def parse_stream(
    expected_write_paths: list[str] | None,
    log_path: str | None,
    quiet: bool,
    model: str | None = None,
    metadata_out: str | None = None,
    reemit_text: bool = False,
) -> int:
    write_invoked = False
    write_paths: list[str] = []
    usage: dict | None = None
    parse_errors = 0
    start = time.time()

    log_fh = open(log_path, "w", encoding="utf-8") if log_path else None

    for raw in sys.stdin:
        if log_fh:
            log_fh.write(raw)
        if not reemit_text:
            # Legacy passthrough: raw events to stdout (the legacy
            # pipeline consumes them via `> /dev/null`).
            sys.stdout.write(raw)
            sys.stdout.flush()

        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue

        if reemit_text:
            # Human-readable live progress (preserves DP6) instead of
            # the raw JSON firehose.
            _emit_assistant_text(event)

        # Detect Write across the three observed event shapes.
        tool_use = None
        etype = event.get("type")
        if etype == "content_block_start":
            cb = event.get("content_block", {}) or {}
            if cb.get("type") == "tool_use":
                tool_use = cb
        elif etype == "tool_use":
            tool_use = event
        elif etype == "assistant":
            for cb in (event.get("message", {}) or {}).get("content", []) or []:
                if isinstance(cb, dict) and cb.get("type") == "tool_use":
                    tool_use = cb
                    break

        if tool_use and (tool_use.get("name") or tool_use.get("tool_name")) == "Write":
            tin = tool_use.get("input") or {}
            path = tin.get("file_path") or tin.get("path") or ""
            if path:
                write_paths.append(path)
                write_invoked = True

        if etype in ("result", "message_stop"):
            u = event.get("usage") or event.get("message", {}).get("usage")
            if u:
                usage = u

    if log_fh:
        log_fh.close()

    elapsed = time.time() - start

    # End-of-run summary
    if not quiet:
        mins, secs = divmod(int(elapsed), 60)
        print("", file=sys.stderr)
        print("─" * 50, file=sys.stderr)
        bits = [f"Adversarial review: {mins:02d}:{secs:02d}"]
        if usage:
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            cache = usage.get("cache_read_input_tokens", 0)
            total_in = in_tok + cache + usage.get("cache_creation_input_tokens", 0)
            bits.append(f"input={total_in:,} output={out_tok:,}")
            cost = _estimate_cost(usage, model)
            if cost is not None:
                bits.append(f"~${cost:.3f}")
            elif model:
                bits.append(f"({model}: no rate table)")
        if parse_errors:
            bits.append(f"parse_errors={parse_errors}")
        print("  " + "  ·  ".join(bits), file=sys.stderr)
        print("─" * 50, file=sys.stderr)
        print("", file=sys.stderr)

    # Programmatic Write verification. With no expected paths, skip it
    # entirely (the call is used for cost/usage capture + text re-emit).
    # With one or more, EACH expected path must have been written.
    if expected_write_paths:
        if not write_invoked:
            print("", file=sys.stderr)
            print(
                f"❌ Write tool was NEVER invoked. Expected target(s): "
                f"{', '.join(expected_write_paths)}",
                file=sys.stderr,
            )
            return 2

        for expected_write_path in expected_write_paths:
            if not _path_was_written(expected_write_path, write_paths):
                print("", file=sys.stderr)
                print(
                    "⚠ Write was invoked but an expected path is missing:",
                    file=sys.stderr,
                )
                print(f"  Expected: {expected_write_path}", file=sys.stderr)
                print(f"  Actual:   {', '.join(write_paths)}", file=sys.stderr)
                for p in write_paths:
                    try:
                        p_resolved = Path(p).resolve()
                        if p_resolved.is_file():
                            print(
                                f"  Recover: mv '{p_resolved}' "
                                f"'{expected_write_path}'",
                                file=sys.stderr,
                            )
                    except (OSError, RuntimeError):
                        pass
                return 3

    # Success — write per-call metadata JSON for the shell-level
    # aggregator to combine across the pipeline (main + critic + fix
    # + re-critic). The aggregator writes ONE cumulative Run Metadata
    # section at end of pipeline.
    if metadata_out:
        meta = {
            "elapsed_seconds": int(elapsed),
        }
        if usage:
            meta["input_tokens"] = usage.get("input_tokens", 0)
            meta["output_tokens"] = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_create = usage.get("cache_creation_input_tokens", 0)
            if cache_read:
                meta["cache_read_tokens"] = cache_read
            if cache_create:
                meta["cache_creation_tokens"] = cache_create
            cost = _estimate_cost(usage, model)
            if cost is not None:
                meta["estimated_cost_usd"] = cost
        if model:
            meta["model"] = model
        if parse_errors:
            meta["parse_errors"] = parse_errors
        _write_metadata_json(Path(metadata_out), meta)

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Parse claude stream-json for Write verification + cost summary."
    )
    p.add_argument("--expected-write-path", action="append", default=None,
                   dest="expected_write_paths",
                   help="Verify Write was invoked on this target. Repeatable "
                        "— each given path must be written (the presentation/"
                        "paper reviewer writes both .md and .json). Omit to "
                        "skip Write verification (cost-capture only).")
    p.add_argument("--log", default=None,
                   help="Write the raw stream-json to this file for debugging.")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the cost summary (still does Write verification).")
    p.add_argument("--model", default=None,
                   help="Model name for cost estimation.")
    p.add_argument("--metadata-out", default=None,
                   help="On success, write per-call metadata JSON to this path. "
                        "The shell pipeline aggregates these across calls and "
                        "writes one cumulative Run Metadata section to the "
                        "final review file.")
    p.add_argument("--reemit-text", action="store_true",
                   help="Re-emit the assistant's streamed TEXT to stdout "
                        "(human-readable live progress) instead of the raw "
                        "JSON events. Used by the presentation/paper review "
                        "path so progress stays visible.")
    args = p.parse_args()

    return parse_stream(
        expected_write_paths=args.expected_write_paths,
        log_path=args.log,
        quiet=args.quiet,
        model=args.model,
        metadata_out=args.metadata_out,
        reemit_text=args.reemit_text,
    )


if __name__ == "__main__":
    sys.exit(main())
