"""`beril-adversarial template-env` — print the CRAFT `.env` config block.

Prints the stereotyped CRAFT runtime-config block to stdout. `configure`
uses this to know what to append to `<BERIL_ROOT>/.env` on first run.

Per CRAFT-CONTRACT.md §3.4 (runtime configuration contract v2), the block
has two parts:

  - A **shared CRAFT block** (provider, credentials, model tiers) that is
    written ONCE per BERIL deployment and shared by every CRAFT skill.
    `configure` detects the `# >>> CRAFT shared config` sentinel and does
    NOT duplicate it if another skill already wrote it.
  - A **per-skill marker** (`BERIL_ADVERSARIAL_CONFIGURED_*`) that each
    skill stamps independently on a successful configure.

`.env` holds app-internal config + secrets and is the single user-facing
source of truth. `configure` GENERATES `<BERIL_ROOT>/.claude/settings.json`
(+ gitignored `settings.local.json` for the token) FROM this block, so that
`claude -p` picks up provider routing and the model-tier aliases natively.
Do not put `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` here — `claude -p`
does not read `.env`; those are generated into settings.json.
"""

from __future__ import annotations

import argparse

from beril_adversarial import __version__


# The shared block is sentinel-delimited so `configure` can detect-and-skip
# when another CRAFT skill already wrote it. Keep the sentinels byte-stable.
SHARED_BLOCK = """\
# >>> CRAFT shared config (written once; shared by all CRAFT skills) >>>
# Edit values here, then re-run any skill's `configure` to regenerate
# <BERIL_ROOT>/.claude/settings.json. See CRAFT-CONTRACT.md §3.4.

# Reasoning provider — routes BOTH `claude -p` and app-internal calls.
# One of:
#   anthropic     your own Anthropic Platform key (works anywhere, off-network)
#   cborg         LBL CBORG gateway (needs LBL network/VPN locally; free on the Hub)
#   subscription  ambient Claude Code login (capped by the monthly Agent SDK credit)
ACTIVE_PROVIDER=cborg

# Provider credentials — set the ONE matching ACTIVE_PROVIDER.
CBORG_API_KEY=                              # <-- paste your CBORG key (cborg)
# ANTHROPIC_API_KEY=                        # <-- your Anthropic Platform key (anthropic)

# CBORG base URL for app-internal (OpenAI-style) calls — keep the /v1.
# NOTE: `claude -p` uses the BARE host (no /v1); configure handles that split.
CBORG_BASE_URL=https://api.cborg.lbl.gov/v1

# Model tiers (Claude-tiered in v1). Leave BLANK → `configure` discovers the
# newest model available on your provider per tier and pins it here (visible +
# reproducible). Set a value to pin your own choice. Models drift (Opus moved
# 4-6 → 4-8; CBORG mirrors with lag), so discovery — not a hardcoded default —
# is the source of truth. reasoning = hard/unrecoverable work; fast = mechanical.
MODEL_REASONING=
MODEL_STANDARD=
MODEL_FAST=

# Optional: BERIL/KBase data auth (only if a review path reads KBase data).
# KBASE_AUTH_TOKEN=

# Optional: image generation (presentation-maker only) — independent provider.
# GOOGLE_AI_STUDIO_API_KEY=
# <<< CRAFT shared config <<<
"""


def _adversarial_block() -> str:
    return f"""\

# --- beril-adversarial-skill (per-skill) ---
# Optional Codex (GPT) review backend for `--reviewer codex`. Codex itself is
# configured in ~/.codex/ (NOT here) — see https://cborg.lbl.gov/tools_codex/.
# adversarial invokes `codex exec --profile <CODEX_PROFILE>` explicitly; never
# rely on the global default `profile =` in ~/.codex/config.toml (fragile).
# CODEX_PROFILE=cborg-gpt-large

# Written by `beril-adversarial configure` on a successful smoke.
# Do not edit by hand; re-run configure to refresh.
BERIL_ADVERSARIAL_CONFIGURED_AT=
BERIL_ADVERSARIAL_CONFIGURED_VERSION=
# beril-adversarial-skill v{__version__}
"""


def render(include_shared: bool = True) -> str:
    """Render the .env block. `configure` calls with include_shared=False
    when the shared sentinel is already present in the target .env."""
    parts = []
    if include_shared:
        parts.append(SHARED_BLOCK)
    parts.append(_adversarial_block())
    return "".join(parts)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "template-env",
        help="Print the CRAFT .env config block.",
        description=(
            "Print the stereotyped CRAFT runtime-config block that "
            "`configure` appends to <BERIL_ROOT>/.env. Use "
            "`--skill-only` to print just this skill's per-skill marker "
            "(omitting the shared CRAFT block)."
        ),
    )
    p.add_argument(
        "--skill-only",
        action="store_true",
        help="Print only the per-skill marker, not the shared CRAFT block.",
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    print(render(include_shared=not getattr(args, "skill_only", False)), end="")
    return 0
