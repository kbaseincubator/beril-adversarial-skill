"""Tests for adversarial's run-record.v1 emitter (Cycle 3 / DP1).

Covers the adversarial-specific divergences from the producer
reference:
- Writes into the TARGET draft's audit/ under adversarial's OWN slots
  (adversarial_run_record.json + adversarial_runs/run-N/) and NEVER
  clobbers the producer's audit/run_record.json + audit/runs/.
- exit-code → status keyed off ADVERSARIAL_CONSUMER_SAFE_EXITS
  (0/2 → completed; 1/3/4 → failed).
- mode=null, user_intent=null, single `review` stage, no halt.
- Round-over-round preservation (each invocation = next run-N).
- The three goldens validate against the shared craft validator
  (graceful-skip when craft-platform isn't editable-installed).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_EMITTER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "beril_adversarial" / "skill" / "tools"
    / "run_record_emitter.py"
)
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "run_record_v1"

# Ensure the package is importable (the emitter imports beril_adversarial).
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src"))


def _load_emitter():
    spec = importlib.util.spec_from_file_location(
        "adv_run_record_emitter", _EMITTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rr = _load_emitter()


def _mk_target_draft(tmp_path: Path, with_producer_record: bool = True) -> Path:
    """A target draft (presmaker/paper-writer) that adversarial reviews.
    Optionally seed the PRODUCER's audit/run_record.json so we can prove
    adversarial never touches it."""
    draft = tmp_path / "talks" / "draft_3"
    (draft / "audit").mkdir(parents=True)
    (draft / "audit" / "adversarial_review.md").write_text(
        "# review", encoding="utf-8")
    if with_producer_record:
        (draft / "audit" / "run_record.json").write_text(
            json.dumps({"PRODUCER": "owned-by-presmaker"}), encoding="utf-8")
    return draft


def _canonical(draft: Path) -> dict:
    return json.loads(
        (draft / "audit" / "adversarial_run_record.json").read_text())


def _try_import_validator():
    try:
        from craft.run_record import validate_run_record  # type: ignore
        return validate_run_record
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Own-slots / never-clobber-producer
# ---------------------------------------------------------------------------

def test_record_start_writes_own_canonical_and_archive(tmp_path):
    draft = _mk_target_draft(tmp_path)
    n = rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    assert n == 1
    rec = _canonical(draft)
    assert rec["skill"] == "adversarial"
    assert rec["run_id"] == "run-1"
    assert rec["status"] == "running"
    assert rec["mode"] is None
    assert rec["artifacts"]["user_intent"] is None
    assert rec["current_stage"] == "review"
    assert [s["id"] for s in rec["stages"]] == ["review"]
    # own archive slot
    assert (draft / "audit" / "adversarial_runs" / "run-1"
            / "run_record.json").is_file()


def test_never_clobbers_producer_record(tmp_path):
    draft = _mk_target_draft(tmp_path, with_producer_record=True)
    rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    rr.record_finalize(draft, exit_code=0)
    # producer's canonical record is byte-for-byte untouched
    prod = json.loads((draft / "audit" / "run_record.json").read_text())
    assert prod == {"PRODUCER": "owned-by-presmaker"}
    # adversarial wrote to its OWN canonical, separate from runs/
    assert (draft / "audit" / "adversarial_run_record.json").is_file()
    assert not (draft / "audit" / "runs").exists()  # producer's, untouched


def test_deliverable_points_at_review_md(tmp_path):
    draft = _mk_target_draft(tmp_path)
    rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    assert _canonical(draft)["artifacts"]["deliverable"] == \
        "audit/adversarial_review.md"


# ---------------------------------------------------------------------------
# exit-code → status (keyed off ADVERSARIAL_CONSUMER_SAFE_EXITS)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exit_code, expected", [
    (0, "completed"),   # clean
    (2, "completed"),   # auto-corrected but consumer-safe
    (1, "failed"),      # user error
    (3, "failed"),      # config error
    (4, "failed"),      # json not consumer-safe
])
def test_exit_code_maps_to_status(tmp_path, exit_code, expected):
    draft = _mk_target_draft(tmp_path)
    rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    rr.record_finalize(draft, exit_code=exit_code)
    rec = _canonical(draft)
    assert rec["status"] == expected
    assert rec["exit_code"] == exit_code  # nuance preserved (0 vs 2)
    assert rec["current_stage"] is None
    assert rec["stages"][0]["status"] == "completed"
    assert rec["finished_at"] is not None


def test_status_helper_keys_off_the_constant():
    # The mapping must follow the constant the emitter resolved at
    # import (rr.ADVERSARIAL_CONSUMER_SAFE_EXITS), not a hardcoded list.
    # Referencing the emitter's own copy (rather than re-importing
    # commands.review here) keeps this robust to suite-wide import
    # state. Pin the expected set too, so a silent widening is caught.
    assert rr.ADVERSARIAL_CONSUMER_SAFE_EXITS == (0, 2)
    for ec in rr.ADVERSARIAL_CONSUMER_SAFE_EXITS:
        assert rr.status_for_exit_code(ec) == "completed"
    for ec in (1, 3, 4):
        assert rr.status_for_exit_code(ec) == "failed"


# ---------------------------------------------------------------------------
# Round-over-round preservation
# ---------------------------------------------------------------------------

def test_each_review_round_allocates_next_run_n(tmp_path):
    """The initial review + each post-revision re-review preserve their
    own archived record (the round-over-round trend signal)."""
    draft = _mk_target_draft(tmp_path)
    rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    rr.record_finalize(draft, exit_code=0)
    n2 = rr.record_start(draft, started_at="2026-06-08T21:00:00Z")
    assert n2 == 2
    rr.record_finalize(draft, exit_code=2)
    runs = sorted(p.name for p in
                  (draft / "audit" / "adversarial_runs").iterdir())
    assert runs == ["run-1", "run-2"]
    # canonical reflects the LATEST round
    assert _canonical(draft)["run_id"] == "run-2"


def test_record_finalize_returns_archive_path_for_subrecord(tmp_path):
    draft = _mk_target_draft(tmp_path)
    rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    out = rr.record_finalize(draft, exit_code=0)
    assert out is not None
    canonical, archive = out
    assert archive == (draft / "audit" / "adversarial_runs" / "run-1"
                       / "run_record.json")
    assert archive.is_file()


def test_finalize_bootstraps_when_no_start(tmp_path):
    """Defensive: record-finalize with no prior record-start still
    produces a coherent terminal record."""
    draft = _mk_target_draft(tmp_path)
    rr.record_finalize(draft, exit_code=0)
    rec = _canonical(draft)
    assert rec["status"] == "completed"
    assert rec["run_id"] == "run-1"


def test_atomic_write_leaves_no_tmp(tmp_path):
    draft = _mk_target_draft(tmp_path)
    rr.record_start(draft, started_at="2026-06-08T20:00:00Z")
    rr.record_finalize(draft, exit_code=0)
    audit = draft / "audit"
    leftovers = list(audit.glob(".*tmp*")) + list(audit.glob("*.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# Goldens + Family-E roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "adversarial_running", "adversarial_completed", "adversarial_failed",
])
def test_golden_parses(name):
    rec = json.loads((_FIXTURES / f"{name}.json").read_text())
    assert rec["schema_version"] == "run-record.v1"
    assert rec["skill"] == "adversarial"


@pytest.mark.parametrize("name", [
    "adversarial_running", "adversarial_completed", "adversarial_failed",
])
def test_golden_validates_against_shared_validator(name):
    validate = _try_import_validator()
    if validate is None:
        pytest.skip(
            "craft-platform not editable-installed alongside; the "
            "Family-E roundtrip runs at craft-platform's conformance "
            "pytest. Locally: pip install -e ../craft-platform"
        )
    rec = json.loads((_FIXTURES / f"{name}.json").read_text())
    assert validate(rec) == []


def test_emitted_lifecycle_validates_against_shared_validator(tmp_path):
    validate = _try_import_validator()
    if validate is None:
        pytest.skip("craft-platform not editable-installed alongside")
    draft = _mk_target_draft(tmp_path)
    # Omit started_at so both start + finish use real wall-clock now —
    # otherwise a fixed future started_at trips the validator's
    # started_at<=finished_at ordering check against real-time finish.
    rr.record_start(draft)
    assert validate(_canonical(draft)) == []
    rr.record_finalize(draft, exit_code=2)  # auto-corrected → completed
    rec = _canonical(draft)
    assert validate(rec) == []
    assert rec["status"] == "completed" and rec["exit_code"] == 2
