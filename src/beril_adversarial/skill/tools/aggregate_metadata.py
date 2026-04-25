#!/usr/bin/env python3
"""Aggregate per-call metadata JSONs and append a Run Metadata section.

The review pipeline produces multiple claude calls (main review +
compliance critic + optional fix pass + post-fix re-critic), each of
which writes a per-call metadata JSON. This tool sums them and writes
one cumulative '## Run Metadata' section to the end of the review
file.

Usage:
    aggregate_metadata.py --review-file PATH --metadata-files JSON [JSON ...]

Each metadata JSON has shape:
    {
        "elapsed_seconds": int,
        "input_tokens": int,
        "output_tokens": int,
        "cache_read_tokens": int (optional),
        "cache_creation_tokens": int (optional),
        "estimated_cost_usd": float (optional),
        "model": str (optional),
        "parse_errors": int (optional)
    }

Aggregation rules:
  - elapsed_seconds: sum
  - input_tokens, output_tokens, cache_*: sum
  - estimated_cost_usd: sum
  - model: first non-empty (should be same across calls anyway)
  - parse_errors: sum

The output section format (appended to end of review file):

    ## Run Metadata

    - **Elapsed**: 11:48
    - **Model**: claude-sonnet-4-20250514
    - **Tokens**: input=1,747,571 output=20,695 (cache_read=590,041)
    - **Estimated cost**: $1.471
    - **Pipeline**: main + critic + fix + re-critic (4 calls)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_metadata(paths: list[Path]) -> list[dict]:
    """Load metadata JSONs that exist; warn for any missing/unreadable."""
    out = []
    for p in paths:
        if not p.is_file():
            print(f"  warn: metadata file missing: {p}", file=sys.stderr)
            continue
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  warn: could not read {p}: {e}", file=sys.stderr)
    return out


def _aggregate(metadata_list: list[dict]) -> dict:
    """Sum numeric fields across calls; preserve model name."""
    agg: dict = {
        "elapsed_seconds": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "estimated_cost_usd": 0.0,
        "parse_errors": 0,
        "call_count": len(metadata_list),
    }
    for m in metadata_list:
        for k in ("elapsed_seconds", "input_tokens", "output_tokens",
                  "cache_read_tokens", "cache_creation_tokens",
                  "parse_errors"):
            agg[k] += m.get(k, 0)
        agg["estimated_cost_usd"] += m.get("estimated_cost_usd", 0.0)
        if "model" not in agg and m.get("model"):
            agg["model"] = m["model"]
    return agg


def _format_section(agg: dict, call_labels: list[str] | None = None) -> str:
    """Format the aggregated metadata as a '## Run Metadata' markdown section."""
    elapsed = agg.get("elapsed_seconds", 0)
    mins, secs = divmod(int(elapsed), 60)

    lines = ["", "## Run Metadata", ""]
    lines.append(f"- **Elapsed**: {mins:02d}:{secs:02d}")
    if "model" in agg:
        lines.append(f"- **Model**: {agg['model']}")
    in_tok = agg.get("input_tokens", 0)
    out_tok = agg.get("output_tokens", 0)
    cache_read = agg.get("cache_read_tokens", 0)
    cache_create = agg.get("cache_creation_tokens", 0)
    line = f"- **Tokens**: input={in_tok:,} output={out_tok:,}"
    extras = []
    if cache_read:
        extras.append(f"cache_read={cache_read:,}")
    if cache_create:
        extras.append(f"cache_create={cache_create:,}")
    if extras:
        line += f" ({', '.join(extras)})"
    lines.append(line)
    cost = agg.get("estimated_cost_usd", 0.0)
    if cost > 0:
        lines.append(f"- **Estimated cost**: ${cost:.3f}")
    if call_labels:
        n = agg.get("call_count", len(call_labels))
        lines.append(f"- **Pipeline**: {' + '.join(call_labels)} ({n} calls)")
    if agg.get("parse_errors"):
        lines.append(f"- **Parse errors**: {agg['parse_errors']}")
    lines.append("")  # trailing newline

    return "\n".join(lines)


def append_aggregate(
    review_file: Path,
    metadata_files: list[Path],
    call_labels: list[str] | None = None,
) -> int:
    """Aggregate metadata and append section to the review file.

    Returns 0 on success, 1 on failure.
    """
    if not review_file.is_file():
        print(f"error: review file missing: {review_file}", file=sys.stderr)
        return 1

    metadata_list = _load_metadata(metadata_files)
    if not metadata_list:
        print("warn: no metadata to aggregate; skipping Run Metadata section",
              file=sys.stderr)
        return 0  # not a failure; just nothing to do

    agg = _aggregate(metadata_list)
    section = _format_section(agg, call_labels=call_labels)

    try:
        text = review_file.read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: could not read review file: {e}", file=sys.stderr)
        return 1

    if not text.endswith("\n"):
        text += "\n"
    new_text = text + section

    try:
        review_file.write_text(new_text, encoding="utf-8")
    except OSError as e:
        print(f"error: could not write review file: {e}", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Aggregate per-call metadata JSONs and append Run Metadata section."
    )
    p.add_argument("--review-file", required=True,
                   help="Absolute path to the review markdown file to update.")
    p.add_argument("--metadata-files", nargs="+", default=[],
                   help="Per-call metadata JSON paths to aggregate.")
    p.add_argument("--call-labels", nargs="+", default=None,
                   help="Optional human-readable labels matching --metadata-files "
                        "(e.g., 'main' 'critic' 'fix' 're-critic').")
    args = p.parse_args()

    return append_aggregate(
        review_file=Path(args.review_file),
        metadata_files=[Path(p) for p in args.metadata_files],
        call_labels=args.call_labels,
    )


if __name__ == "__main__":
    sys.exit(main())
