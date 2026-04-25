"""`beril-adversarial configure` — minimal environment check.

Verify that the `claude` CLI is installed. That's the only hard
requirement; everything else (WebSearch, codex, MCP servers) is
discovered at first-review-run time and surfaces clear errors there.
The over-engineered probe machinery from earlier drafts has been cut.

Exit codes:
  0 — claude is present
  3 — claude not on PATH
"""

from __future__ import annotations

import argparse
import shutil
import sys

from beril_adversarial import __version__, discovery


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "configure",
        help="Verify the claude CLI is installed.",
        description=(
            "Quick check that the `claude` CLI is on PATH. The actual "
            "review run will surface any further configuration issues "
            "(codex availability, MCP servers, WebSearch) with clear "
            "error messages — no point in elaborate pre-flight."
        ),
    )
    p.add_argument(
        "--beril-root",
        help="Explicit BERIL_ROOT (used only for the status banner).",
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    # Resolve BERIL_ROOT for the banner; non-fatal if absent.
    try:
        beril_root = discovery.find_beril_root(explicit=getattr(args, "beril_root", None))
    except discovery.BerilRootNotFound:
        beril_root = None

    print(f"beril-adversarial-skill v{__version__}")
    if beril_root is not None:
        print(f"  BERIL_ROOT: {beril_root}")

    claude_path = shutil.which("claude")
    if claude_path is None:
        print("  [MISSING] claude CLI not found on PATH.", file=sys.stderr)
        print("  Install Claude Code (https://docs.claude.com) and retry.",
              file=sys.stderr)
        return 3

    print(f"  [OK]      claude — {claude_path}")

    codex_path = shutil.which("codex")
    if codex_path:
        print(f"  [OK]      codex  — {codex_path}  (enables --reviewer codex/claude,codex)")
    else:
        print(f"  [absent]  codex  — not on PATH; --reviewer codex unavailable")

    return 0
