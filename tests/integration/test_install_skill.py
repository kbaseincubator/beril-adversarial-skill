"""Integration tests for `beril-adversarial install-skill`.

Marked @pytest.mark.integration because they shell out to the installed
package. Run with: pytest -m integration tests/integration/test_install_skill.py
"""

from __future__ import annotations

import argparse
import stat
from pathlib import Path

import pytest

from beril_adversarial.commands import install_skill


pytestmark = pytest.mark.integration


def test_install_skill_creates_full_tree(synthetic_beril_root: Path):
    """install-skill writes SKILL.md, all subdirs, and creates state/."""
    args = argparse.Namespace(
        beril_root=str(synthetic_beril_root),
        force=False,
        no_smoke_test=True,
    )
    rc = install_skill.run(args)
    assert rc == 0

    skill_dir = synthetic_beril_root / ".claude" / "skills" / "beril-adversarial"
    assert skill_dir.is_dir()

    # Top-level file
    assert (skill_dir / "SKILL.md").is_file()

    # Shipped subdirs
    for subdir in ("commands", "prompts", "references", "tools"):
        assert (skill_dir / subdir).is_dir(), f"missing {subdir}/"

    # Specific shipped files
    assert (skill_dir / "commands" / "beril-adversarial.md").is_file()
    assert (skill_dir / "commands" / "beril-adversarial-configure.md").is_file()
    assert (skill_dir / "prompts" / "adversarial_project.v1.md").is_file()
    assert (skill_dir / "prompts" / "adversarial_plan.v1.md").is_file()
    assert (skill_dir / "prompts" / "adversarial_paper.v1.md").is_file()
    assert (skill_dir / "prompts" / "fusion.v1.md").is_file()
    assert (skill_dir / "prompts" / "consolidation.v1.md").is_file()
    assert (skill_dir / "references" / "adversarial-checklist.md").is_file()
    assert (skill_dir / "tools" / "adversarial_review.sh").is_file()

    # Local subdirs created
    assert (skill_dir / "state").is_dir()
    assert (skill_dir / "state" / "README.md").is_file()


def test_install_skill_sets_executable_bit_on_shell_script(
    synthetic_beril_root: Path,
):
    """The shipped shell script must be executable after install."""
    args = argparse.Namespace(
        beril_root=str(synthetic_beril_root),
        force=False,
        no_smoke_test=True,
    )
    install_skill.run(args)

    script = (
        synthetic_beril_root / ".claude" / "skills" / "beril-adversarial"
        / "tools" / "adversarial_review.sh"
    )
    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR, "owner exec bit not set"
    # Group/other exec are also set by _set_executable_bits; check at least one.
    assert mode & (stat.S_IXGRP | stat.S_IXOTH), "group/other exec bits not set"


def test_install_skill_preserves_state_on_reinstall(synthetic_beril_root: Path):
    """state/ contents must survive a re-install."""
    args = argparse.Namespace(
        beril_root=str(synthetic_beril_root),
        force=False,
        no_smoke_test=True,
    )
    install_skill.run(args)

    # User writes a learned-pattern entry to state/
    state_file = (
        synthetic_beril_root / ".claude" / "skills" / "beril-adversarial"
        / "state" / "learned-patterns.md"
    )
    state_file.write_text("# Test pattern entry\n", encoding="utf-8")

    # Reinstall with --force
    args.force = True
    rc = install_skill.run(args)
    assert rc == 0

    # state contents preserved
    assert state_file.is_file()
    assert state_file.read_text(encoding="utf-8") == "# Test pattern entry\n"


def test_install_skill_overwrites_shipped_subdirs_on_force(
    synthetic_beril_root: Path,
):
    """Shipped subdirs (prompts/, references/, etc.) get re-copied on --force."""
    args = argparse.Namespace(
        beril_root=str(synthetic_beril_root),
        force=False,
        no_smoke_test=True,
    )
    install_skill.run(args)

    skill_dir = synthetic_beril_root / ".claude" / "skills" / "beril-adversarial"
    prompt_file = skill_dir / "prompts" / "adversarial_project.v1.md"

    # User edits a shipped file (this should be undone on reinstall)
    prompt_file.write_text("USER EDITED — should be overwritten\n", encoding="utf-8")

    args.force = True
    install_skill.run(args)

    # File is back to shipped content
    content = prompt_file.read_text(encoding="utf-8")
    assert "USER EDITED" not in content
    assert "BERIL Adversarial Reviewer" in content


def test_install_skill_fails_on_invalid_beril_root(tmp_path: Path):
    """Non-BERIL paths should fail discovery and return exit code 1."""
    not_beril = tmp_path / "not_beril"
    not_beril.mkdir()
    args = argparse.Namespace(
        beril_root=str(not_beril),
        force=False,
        no_smoke_test=True,
    )
    rc = install_skill.run(args)
    assert rc == 1
