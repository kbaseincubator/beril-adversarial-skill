"""`beril-adversarial install-skill <BERIL_ROOT>` — copy shipped skill files into BERIL.

Copies SKILL.md, commands/, prompts/, references/, and tools/ from the
installed package's bundled skill data into
`<BERIL_ROOT>/.claude/skills/beril-adversarial/`.

PRESERVES (never overwritten): state/  (runtime state including learned-patterns.md).
CREATES if missing: state/.

Sets executable bit on tools/adversarial_review.sh after copy
(belt-and-suspenders even though hatchling should preserve it through
the wheel).

After copy succeeds: optionally runs a LIGHT post-install check —
verifies the `claude` CLI is on PATH and prints a pointer to the next
step. This intentionally does NOT invoke `configure`: configure has
side effects (extends `.env`, writes `.claude/settings.json`, runs a
live `claude -p` ping) that must not run silently as a sub-step of
install-skill. The user runs `beril-adversarial configure --beril-root
<root>` themselves, when they're ready.

Honors --no-smoke-test by skipping the post-install check entirely.
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
from importlib import resources
from pathlib import Path

from beril_adversarial import __version__, discovery

# Directories inside the shipped skill/ dir that should be overwritten on install
_SHIPPED_SUBDIRS = ("commands", "prompts", "references", "tools")

# Directories that must exist in the installed skill dir but are install-local
# (never shipped, never overwritten)
_LOCAL_SUBDIRS = ("state",)

# Files at the skill-dir root that ship
_SHIPPED_FILES = ("SKILL.md",)

# Files inside shipped subdirs that need executable bit set after copy
_EXECUTABLE_FILES = (
    "tools/adversarial_review.sh",
    "tools/stream_progress.py",
    "tools/aggregate_metadata.py",
    "tools/verify_citations.py",
    "tools/validate_presentation_review.py",
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "install-skill",
        help="Copy shipped skill files into a BERIL checkout.",
        description=(
            "Copy the beril-adversarial skill files from the installed package "
            "into <BERIL_ROOT>/.claude/skills/beril-adversarial/. "
            "Preserves the install-local state/ subdirectory."
        ),
    )
    p.add_argument(
        "beril_root",
        nargs="?",
        default=".",
        help="Path to the BERIL checkout root (default: current directory).",
    )
    p.add_argument(
        "--force",
        "-f",
        action="store_true",
        help=(
            "Overwrite shipped files without confirmation. Does NOT remove "
            "the install-local state/ subdirectory."
        ),
    )
    p.add_argument(
        "--no-smoke-test",
        action="store_true",
        help=(
            "Skip the post-install light check (claude on PATH + next-step "
            "hint). Default: run it advisory (non-fatal)."
        ),
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace) -> int:
    try:
        beril_root = discovery.find_beril_root(explicit=args.beril_root)
    except discovery.BerilRootNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    skill_target = discovery.get_skill_dir(beril_root)
    skill_target.mkdir(parents=True, exist_ok=True)

    # Locate the shipped skill/ dir inside the installed package.
    try:
        skill_src_trav = resources.files("beril_adversarial") / "skill"
    except Exception as e:
        print(
            f"Error: could not locate shipped skill data inside "
            f"beril_adversarial package: {e}. "
            f"This is an install-level bug. Please file an issue.",
            file=sys.stderr,
        )
        return 2

    with resources.as_file(skill_src_trav) as skill_src:
        if not skill_src.is_dir():
            print(
                f"Error: shipped skill data at {skill_src} is not a directory. "
                f"Package build may be broken.",
                file=sys.stderr,
            )
            return 2

        _copy_shipped_files(skill_src, skill_target, force=args.force)
        _copy_shipped_subdirs(skill_src, skill_target, force=args.force)
        _set_executable_bits(skill_target)

    _ensure_local_subdirs(skill_target)

    print(f"Skill files installed to: {skill_target}")
    print(f"Preserved (never overwritten): {', '.join(_LOCAL_SUBDIRS)}")
    print(f"Package version: {__version__}")

    if args.no_smoke_test:
        return 0

    # Light post-install check — advisory, NEVER invokes configure.
    # configure has real side effects (extends .env, writes
    # .claude/settings.json + settings.local.json, runs a live
    # `claude -p` ping) and must not run silently as a sub-step of
    # install-skill. The Hub crash that motivated this decoupling
    # was install-skill calling configure.run() and that path
    # AttributeError'ing on a Namespace built without the
    # --no-discover / --no-ping / --yes flags.
    print("")
    claude_path = shutil.which("claude")
    if claude_path is None:
        print(
            "  [WARN] claude CLI not found on PATH. Install Claude Code "
            "(https://docs.claude.com) before running configure.",
            file=sys.stderr,
        )
    else:
        print(f"  [OK] claude — {claude_path}")
    print("")
    print(
        f"Next: run `beril-adversarial configure --beril-root {beril_root}` "
        "to bootstrap CRAFT runtime config."
    )
    return 0


def _copy_shipped_files(src: Path, dst: Path, *, force: bool) -> None:
    for name in _SHIPPED_FILES:
        s = src / name
        if not s.is_file():
            continue
        d = dst / name
        if d.exists() and not force and _files_identical(s, d):
            continue
        shutil.copy2(s, d)


def _copy_shipped_subdirs(src: Path, dst: Path, *, force: bool) -> None:
    for subdir in _SHIPPED_SUBDIRS:
        s = src / subdir
        if not s.is_dir():
            continue
        d = dst / subdir
        # Full replacement: remove and re-copy. Preserve nothing inside
        # shipped subdirs — they're maintained by the package.
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(s, d)


def _set_executable_bits(skill_dir: Path) -> None:
    """Ensure shipped shell scripts have +x. Hatchling should preserve this
    through the wheel, but we set it explicitly as a safety net."""
    for rel in _EXECUTABLE_FILES:
        path = skill_dir / rel
        if path.is_file():
            current = path.stat().st_mode
            path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _ensure_local_subdirs(skill_dir: Path) -> None:
    for subdir in _LOCAL_SUBDIRS:
        p = skill_dir / subdir
        p.mkdir(exist_ok=True)
    # Write a starter README for state/ on first creation.
    state_readme = skill_dir / "state" / "README.md"
    if not state_readme.exists():
        state_readme.write_text(_STATE_README, encoding="utf-8")


def _files_identical(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


_STATE_README = """# state/ — install-local runtime state

Files in this directory are written at runtime by the adversarial
reviewer and are NEVER shipped or overwritten by `beril-adversarial
install-skill`.

## learned-patterns.md

Cross-project meta-memory of review patterns. Written by the reviewer
when it identifies a novel generalizable review pattern (NOT
project-specific gotchas — those go in `<BERIL>/docs/pitfalls.md`).

Read at the start of every review and used as pattern-recognition
starting material. See `references/adversarial-checklist.md` and the
system prompts for the protocol.

Maintainer note: when this file approaches the size cap (~15K tokens),
move the current contents to
`state/learned-patterns-archive/YYYY-MM-DD.md` and consolidate into a
shorter live file.
"""
