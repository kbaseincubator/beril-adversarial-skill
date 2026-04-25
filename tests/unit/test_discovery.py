"""Unit tests for BERIL_ROOT discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from beril_adversarial import discovery


def _build_beril_root(base: Path, *, with_env: bool = True,
                     core_skills: tuple[str, ...] = ("submit",)) -> Path:
    """Helper: build a BERIL-marker-valid directory at base."""
    base.mkdir(parents=True, exist_ok=True)
    if with_env:
        (base / ".env").write_text("# test\n")
    skills = base / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for s in core_skills:
        d = skills / s
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text(f"# {s}\n")
    return base


class TestExplicitPath:

    def test_valid_explicit_path_resolves(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril")
        result = discovery.find_beril_root(explicit=root)
        assert result == root.resolve()

    def test_invalid_explicit_path_raises(self, tmp_path: Path):
        bad = tmp_path / "not_beril"
        bad.mkdir()
        with pytest.raises(discovery.BerilRootNotFound) as exc_info:
            discovery.find_beril_root(explicit=bad)
        # The diagnostic should name what was missing.
        assert "Marker check" in str(exc_info.value)

    def test_missing_env_file_fails(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril", with_env=False)
        with pytest.raises(discovery.BerilRootNotFound):
            discovery.find_beril_root(explicit=root)

    def test_missing_core_skills_fails(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril", core_skills=())
        with pytest.raises(discovery.BerilRootNotFound):
            discovery.find_beril_root(explicit=root)


class TestEnvVar:

    def test_env_var_resolves(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "from_env")
        env = {"BERIL_ROOT": str(root)}
        result = discovery.find_beril_root(env=env)
        assert result == root.resolve()

    def test_invalid_env_var_raises(self, tmp_path: Path):
        bad = tmp_path / "not_beril_from_env"
        bad.mkdir()
        env = {"BERIL_ROOT": str(bad)}
        with pytest.raises(discovery.BerilRootNotFound):
            discovery.find_beril_root(env=env)

    def test_explicit_overrides_env(self, tmp_path: Path):
        env_root = _build_beril_root(tmp_path / "env_root")
        explicit_root = _build_beril_root(tmp_path / "explicit_root")
        env = {"BERIL_ROOT": str(env_root)}
        result = discovery.find_beril_root(explicit=explicit_root, env=env)
        assert result == explicit_root.resolve()


class TestWalkUp:

    def test_walk_up_finds_root_from_subdir(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril")
        nested = root / "projects" / "foo" / "subfolder"
        nested.mkdir(parents=True)
        result = discovery.find_beril_root(env={}, cwd=nested)
        assert result == root.resolve()

    def test_walk_up_finds_root_at_cwd_itself(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril")
        result = discovery.find_beril_root(env={}, cwd=root)
        assert result == root.resolve()

    def test_walk_up_fails_when_no_match(self, tmp_path: Path):
        # Nothing BERIL-shaped under tmp_path
        with pytest.raises(discovery.BerilRootNotFound) as exc_info:
            discovery.find_beril_root(env={}, cwd=tmp_path)
        # Diagnostic should mention walk-up
        assert "Walk-up" in str(exc_info.value) or "walk-up" in str(exc_info.value)


class TestMarkerCheck:

    def test_tiebreaker_directory_name(self, tmp_path: Path):
        root = tmp_path / "BERIL-research-observatory"
        _build_beril_root(root)
        check = discovery._check_markers(root)
        assert "directory-name-matches-BERIL" in check.tiebreakers

    def test_tiebreaker_env_example(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril")
        (root / ".env.example").write_text(
            "KBASE_AUTH_TOKEN=YOUR_KEY_HERE\n"
        )
        check = discovery._check_markers(root)
        assert ".env.example-has-KBASE_AUTH_TOKEN" in check.tiebreakers

    def test_tiebreaker_directory_structure(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril")
        (root / "DIRECTORY_STRUCTURE.md").write_text("# Structure\n")
        check = discovery._check_markers(root)
        assert "DIRECTORY_STRUCTURE.md-present" in check.tiebreakers

    def test_marker_score_increases_with_signals(self, tmp_path: Path):
        bare = _build_beril_root(tmp_path / "bare")
        rich = _build_beril_root(
            tmp_path / "BERIL-rich",
            core_skills=("submit", "berdl", "suggest-research"),
        )
        (rich / ".env.example").write_text("KBASE_AUTH_TOKEN=x\n")
        (rich / "DIRECTORY_STRUCTURE.md").write_text("# x\n")

        bare_check = discovery._check_markers(bare)
        rich_check = discovery._check_markers(rich)
        assert discovery._marker_score(rich_check) > discovery._marker_score(bare_check)


class TestDerivedPaths:

    def test_skill_dir(self, tmp_path: Path):
        root = tmp_path / "beril"
        skill = discovery.get_skill_dir(root)
        assert skill == root / ".claude" / "skills" / "beril-adversarial"

    def test_prompts_references_tools_state(self, tmp_path: Path):
        root = tmp_path / "beril"
        skill = discovery.get_skill_dir(root)
        assert discovery.get_prompts_dir(root) == skill / "prompts"
        assert discovery.get_references_dir(root) == skill / "references"
        assert discovery.get_tools_dir(root) == skill / "tools"
        assert discovery.get_state_dir(root) == skill / "state"

    def test_resolve_paths_bundle(self, tmp_path: Path):
        root = _build_beril_root(tmp_path / "beril")
        bundle = discovery.resolve_paths(explicit=root)
        assert bundle.beril_root == root.resolve()
        assert bundle.skill_dir.name == "beril-adversarial"
        assert bundle.prompts_dir == bundle.skill_dir / "prompts"
        assert bundle.tools_dir == bundle.skill_dir / "tools"
