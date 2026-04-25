"""Shared pytest fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def synthetic_beril_root(tmp_path: Path) -> Path:
    """Build a minimal but marker-valid BERIL root in a temp directory.

    Includes:
      - .env file (presence, not content)
      - .env.example with KBASE_AUTH_TOKEN tiebreaker
      - .claude/skills/submit/SKILL.md, .claude/skills/berdl/SKILL.md
      - projects/sample_project/ with README, RESEARCH_PLAN, REPORT
      - DIRECTORY_STRUCTURE.md tiebreaker

    Returns the absolute path to the synthetic BERIL root.
    """
    root = tmp_path / "synthetic_beril"
    root.mkdir()

    (root / ".env").write_text("# synthetic\n", encoding="utf-8")
    (root / ".env.example").write_text(
        "KBASE_AUTH_TOKEN=...\n", encoding="utf-8"
    )
    (root / "DIRECTORY_STRUCTURE.md").write_text(
        "# Synthetic BERIL\n", encoding="utf-8"
    )

    # BERIL-core skill markers.
    skills = root / ".claude" / "skills"
    skills.mkdir(parents=True)
    for name in ("submit", "berdl", "suggest-research"):
        d = skills / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n# {name}\n", encoding="utf-8"
        )

    # Sample project for review-type tests.
    proj = root / "projects" / "sample_project"
    proj.mkdir(parents=True)
    (proj / "README.md").write_text(
        "# Sample Project\n\n## Status\nIn Progress\n\n"
        "## Research Question\nWhat is X?\n\n"
        "## Authors\n- Test Author\n",
        encoding="utf-8",
    )
    (proj / "RESEARCH_PLAN.md").write_text(
        "# Research Plan\n\n## Hypothesis\nX is Y.\n", encoding="utf-8"
    )
    (proj / "REPORT.md").write_text(
        "# Report\n\n## Key Findings\nX appears to be Y.\n",
        encoding="utf-8",
    )
    (proj / "notebooks").mkdir()
    (proj / "figures").mkdir()
    (proj / "data").mkdir()

    return root
