"""Unit tests for tools/validate_presentation_review.py.

Replicates paper-writer's post-checker test pattern. Tests cover:
  - Pass case (a minimal valid review)
  - Schema literal mismatch
  - Missing required field on a finding
  - Summary count mismatch
  - Duplicate finding IDs
  - Advisory: zero P0s on a large deck
  - Advisory: missing narrative_weakness
  - Hard error: narrative_weakness with non-info severity
  - Hard error: extra info severity on a non-narrative_weakness finding
  - JSON file unparseable (returns exit 1)
  - File not found (exit 3)
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_DIR_SRC = (
    Path(__file__).parent.parent.parent
    / "src"
    / "beril_adversarial"
    / "skill"
)
VALIDATOR_PATH = SKILL_DIR_SRC / "tools" / "validate_presentation_review.py"


# Load the validator module by file path so we can call validate()
# directly without subprocess overhead in most tests.
def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "_validate_presentation_review", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_validate_presentation_review"] = mod
    spec.loader.exec_module(mod)
    return mod


validator = _load_validator_module()


def _make_finding(
    fid="F001",
    cls="claim_evidence",
    severity="P1",
    confidence="high",
    slide_id=9,
    slide_position=9,
    slide_layout="data_figure",
    title_quote="Some claim",
    issue="some issue",
    fix_target="slide_compose.v1.md",
    fix_hint="some fix",
    **extra,
):
    """Build a minimum-valid slide-level finding dict."""
    f = {
        "id": fid,
        "class": cls,
        "severity": severity,
        "confidence": confidence,
        "slide_id": slide_id,
        "slide_position": slide_position,
        "slide_layout": slide_layout,
        "title_quote": title_quote,
        "issue": issue,
        "fix_target": fix_target,
        "fix_hint": fix_hint,
    }
    f.update(extra)
    return f


def _make_deck_finding(
    fid="DL001",
    cls="missing_slide",
    severity="P1",
    confidence="high",
    issue="missing X",
    fix_target="slide_compose.v1.md",
    fix_hint="add slide",
    **extra,
):
    """Build a minimum-valid deck-level finding dict (no slide_*)."""
    f = {
        "id": fid,
        "class": cls,
        "severity": severity,
        "confidence": confidence,
        "issue": issue,
        "fix_target": fix_target,
        "fix_hint": fix_hint,
    }
    f.update(extra)
    return f


def _make_doc(findings=None, deck_findings=None, summary=None):
    """Build a minimum-valid top-level document, with summary auto-derived
    from findings if not specified explicitly."""
    findings = findings or []
    deck_findings = deck_findings or []
    if summary is None:
        from collections import Counter

        sev = Counter(f["severity"] for f in findings + deck_findings)
        cls = Counter(f["class"] for f in findings + deck_findings)
        summary = {
            "total_findings": len(findings) + len(deck_findings),
            "by_severity": dict(sev),
            "by_class": dict(cls),
        }
    return {
        "schema_version": "adversarial-review-presentation.v1",
        "draft_dir": "/tmp/fake",
        "project_id": "fake_project",
        "draft_number": 1,
        "reviewed_at": "2026-04-28T13:42:00Z",
        "reviewer_model": "claude-sonnet-4-20250514",
        "prompt_version": "adversarial_presentation.v1",
        "tier": "STRONG",
        "summary": summary,
        "findings": findings,
        "deck_level_findings": deck_findings,
    }


# ============================================================================
# Pass cases
# ============================================================================


def test_minimal_valid_doc_passes():
    """A doc with one slide finding + the required narrative_weakness
    deck finding (severity=info) should validate clean."""
    doc = _make_doc(
        findings=[_make_finding()],
        deck_findings=[
            _make_deck_finding(
                fid="DL001", cls="narrative_weakness", severity="info"
            )
        ],
    )
    errors, warnings, stats = validator.validate(doc)
    assert errors == [], f"unexpected errors: {errors}"
    assert stats["slide_findings"] == 1
    assert stats["deck_findings"] == 1
    # warnings is OK (zero P0s on a 1-slide deck won't trip the threshold)


def test_empty_findings_warns_not_errors():
    """Zero findings is a warning (reviewer almost certainly skipped
    detection) but not a hard error — caller decides."""
    doc = _make_doc()
    errors, warnings, stats = validator.validate(doc)
    assert errors == []
    assert any("zero findings" in w for w in warnings)


# ============================================================================
# Schema-literal validation
# ============================================================================


def test_schema_version_mismatch_fails():
    doc = _make_doc()
    doc["schema_version"] = "adversarial-review-presentation.v2"
    errors, _, _ = validator.validate(doc)
    assert any("schema_version" in e for e in errors)


def test_schema_version_missing_fails():
    doc = _make_doc()
    del doc["schema_version"]
    errors, _, _ = validator.validate(doc)
    assert any("schema_version" in e for e in errors)


# ============================================================================
# Required-field validation
# ============================================================================


def test_missing_required_field_on_slide_finding_fails():
    """An incomplete finding must be flagged."""
    bad = _make_finding()
    del bad["fix_target"]
    doc = _make_doc(findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("fix_target" in e for e in errors)


def test_missing_slide_level_field_fails():
    """slide-level findings need slide_id + slide_position + slide_layout
    + title_quote."""
    bad = _make_finding()
    del bad["slide_id"]
    doc = _make_doc(findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("slide_id" in e for e in errors)


def test_deck_level_finding_doesnt_need_slide_fields():
    """deck_level_findings lack a single slide locus; they should NOT
    be flagged for missing slide_id et al."""
    deck = _make_deck_finding(cls="narrative_weakness", severity="info")
    doc = _make_doc(deck_findings=[deck])
    errors, _, _ = validator.validate(doc)
    # No errors should mention slide_id specifically for the deck finding.
    for e in errors:
        if "slide_id" in e:
            assert "deck_level" not in e, (
                f"deck-level finding spuriously flagged for slide_id: {e}"
            )


def test_invalid_class_value_fails():
    bad = _make_finding(cls="invented_class")
    doc = _make_doc(findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("class=" in e and "invented_class" in e for e in errors)


def test_invalid_severity_value_fails():
    bad = _make_finding(severity="P3")  # P3 is not a valid severity
    doc = _make_doc(findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("severity=" in e and "P3" in e for e in errors)


def test_invalid_confidence_value_fails():
    bad = _make_finding(confidence="certain")
    doc = _make_doc(findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("confidence=" in e for e in errors)


# ============================================================================
# Summary-count consistency
# ============================================================================


def test_summary_total_mismatch_fails():
    doc = _make_doc(findings=[_make_finding()])
    doc["summary"]["total_findings"] = 99  # actual is 1
    errors, _, _ = validator.validate(doc)
    assert any("total_findings" in e for e in errors)


def test_summary_by_severity_mismatch_fails():
    doc = _make_doc(findings=[_make_finding(severity="P1")])
    doc["summary"]["by_severity"] = {"P0": 99, "P1": 1}  # P0 fabricated
    errors, _, _ = validator.validate(doc)
    assert any("by_severity" in e and "P0" in e for e in errors)


def test_summary_by_class_mismatch_fails():
    doc = _make_doc(findings=[_make_finding(cls="claim_evidence")])
    doc["summary"]["by_class"] = {"claim_evidence": 1, "throughline": 5}
    errors, _, _ = validator.validate(doc)
    assert any("by_class" in e and "throughline" in e for e in errors)


def test_summary_missing_severity_key_for_present_findings_fails():
    """If a severity appears in findings but is absent from summary.by_severity,
    that's a count mismatch the reviewer has to fix."""
    doc = _make_doc(findings=[_make_finding(severity="P0")])
    doc["summary"]["by_severity"] = {"P1": 0}  # missing P0 entirely
    errors, _, _ = validator.validate(doc)
    assert any("by_severity" in e and "P0" in e for e in errors)


# ============================================================================
# ID uniqueness
# ============================================================================


def test_duplicate_finding_id_fails():
    doc = _make_doc(
        findings=[
            _make_finding(fid="F001"),
            _make_finding(fid="F001", cls="register_drift"),
        ]
    )
    errors, _, _ = validator.validate(doc)
    assert any("duplicate" in e.lower() and "F001" in e for e in errors)


# ============================================================================
# narrative_weakness invariants
# ============================================================================


def test_narrative_weakness_with_non_info_severity_fails():
    bad = _make_deck_finding(cls="narrative_weakness", severity="P0")
    doc = _make_doc(deck_findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("narrative_weakness" in e and "info" in e for e in errors)


def test_info_severity_on_non_narrative_weakness_fails():
    bad = _make_finding(severity="info")  # info reserved for narrative_weakness
    doc = _make_doc(findings=[bad])
    errors, _, _ = validator.validate(doc)
    assert any("info" in e and "narrative_weakness" in e for e in errors)


def test_two_narrative_weakness_findings_fails():
    """Class 7 must produce exactly one finding; multiple is wrong."""
    doc = _make_doc(
        deck_findings=[
            _make_deck_finding(
                fid="DL001", cls="narrative_weakness", severity="info"
            ),
            _make_deck_finding(
                fid="DL002", cls="narrative_weakness", severity="info"
            ),
        ]
    )
    errors, _, _ = validator.validate(doc)
    assert any("narrative_weakness" in e and "exactly once" in e for e in errors)


def test_missing_narrative_weakness_warns_not_fails():
    """Reviewer might skip Class 7; that's a warning, not a hard fail."""
    doc = _make_doc(findings=[_make_finding()])
    errors, warnings, _ = validator.validate(doc)
    assert errors == []
    assert any("narrative_weakness" in w for w in warnings)


# ============================================================================
# Advisory checks
# ============================================================================


def test_zero_p0_on_large_deck_warns():
    """Spec §9 lists 3 P0s for draft_9 (26 slides). A zero-P0 review on
    a 20+ slide deck strongly suggests reviewer under-fire."""
    doc = _make_doc(
        findings=[_make_finding(severity="P1", slide_position=25)],
        deck_findings=[
            _make_deck_finding(
                fid="DL001", cls="narrative_weakness", severity="info"
            )
        ],
    )
    errors, warnings, _ = validator.validate(doc)
    assert errors == []
    assert any("P0" in w and "under-fire" in w for w in warnings)


def test_zero_p0_on_small_deck_no_warn():
    """A small deck (<20 slides) reasonably has no P0s; don't warn."""
    doc = _make_doc(
        findings=[_make_finding(severity="P1", slide_position=5)],
        deck_findings=[
            _make_deck_finding(
                fid="DL001", cls="narrative_weakness", severity="info"
            )
        ],
    )
    errors, warnings, _ = validator.validate(doc)
    assert errors == []
    assert not any("under-fire" in w for w in warnings)


# ============================================================================
# CLI subprocess tests
# ============================================================================


def test_cli_pass_returns_zero(tmp_path: Path):
    p = tmp_path / "review.json"
    doc = _make_doc(
        findings=[_make_finding()],
        deck_findings=[
            _make_deck_finding(
                fid="DL001", cls="narrative_weakness", severity="info"
            )
        ],
    )
    p.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(p)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"unexpected non-zero exit: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "PASS" in result.stdout


def test_cli_missing_file_exits_3(tmp_path: Path):
    p = tmp_path / "nonexistent.json"
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(p)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 3
    assert "not found" in result.stderr


def test_cli_unparseable_json_exits_1(tmp_path: Path):
    p = tmp_path / "broken.json"
    p.write_text("{ this is not json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(p)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "not valid JSON" in result.stderr


def test_cli_validation_failure_exits_1(tmp_path: Path):
    p = tmp_path / "review.json"
    doc = _make_doc(findings=[_make_finding()])
    doc["schema_version"] = "wrong"
    p.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(p)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "FAIL" in result.stderr


def test_cli_warnings_exit_2(tmp_path: Path):
    """Validator should exit 2 (advisory) when there are warnings but
    no errors."""
    p = tmp_path / "review.json"
    # Findings present, narrative_weakness missing → triggers warning only
    doc = _make_doc(findings=[_make_finding()])
    p.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(p)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "PASS" in result.stdout
    assert "WARN" in result.stderr


def test_cli_handles_path_with_special_chars(tmp_path: Path):
    """Heredoc-quoting fix: validator must accept paths that would
    have broken the old inline shell heredoc."""
    weird = tmp_path / "review with spaces.json"
    doc = _make_doc(
        findings=[_make_finding()],
        deck_findings=[
            _make_deck_finding(
                fid="DL001", cls="narrative_weakness", severity="info"
            )
        ],
    )
    weird.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(weird)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"path with spaces broke validator: {result.stderr}"
