#!/usr/bin/env python3
"""run_record_emitter.py — adversarial's `run-record.v1` emitter
(Cycle 3 / DP1, 2026-06-08).

Projects an adversarial review's run-end state into the cross-skill
`run-record.v1` contract (schema + validator of record live in
craft-platform `craft.run_record`; this skill does NOT import that
package at runtime — the emitter CORE is COPY-ADAPTED here per the
copy-not-share convention, the same as llm_config.py / stream_progress.py
/ aggregate_metadata.py). The shared *record* is contracted; each
skill's *emitter* differs.

Reference emitter: presentation-maker's finalize_run.py (Step 2) +
paper-writer's run_record_emitter.py (Step 4). This is the third — and
the biggest divergence — because adversarial is a REVIEWER, not a
producer: it has no draft layout of its own, runs single-pass, and
writes INTO the target draft it is reviewing.

Adversarial divergences from the producer reference
---------------------------------------------------
* **Standalone / no draft layout.** adversarial reviews a TARGET draft
  (a presentation-maker or paper-writer draft) and writes its review
  into the target's `audit/`. The producer OWNS `audit/run_record.json`
  + `audit/runs/`; adversarial must NEVER clobber those. So adversarial
  writes to its OWN, separate slots:
    canonical:  <draft_dir>/audit/adversarial_run_record.json
    archive:    <draft_dir>/audit/adversarial_runs/run-N/run_record.json
  where N is adversarial's OWN monotonic counter, scoped to
  `adversarial_runs/` so it never collides with the producer's
  `runs/`. Each invocation (the initial review + every post-revision
  re-review in the producer's iterate loop) increments N, preserving
  the round-over-round trend (the DP8 / defensibility signal).
  The parent's adversarial stage entry points at a specific round via
  stages[].subrecord = "audit/adversarial_runs/run-N/run_record.json"
  (the PARENT writes that pointer; record-finalize prints the archive
  path so the caller can wire it).

* **exit-code → status, keyed off the skill's own constant.** A review
  is "completed" iff it produced a CONSUMER-SAFE deliverable —
  exit_code ∈ ADVERSARIAL_CONSUMER_SAFE_EXITS (0=clean, 2=auto-
  corrected); else "failed" (1 user-error, 3 config, 4 json-unsafe).
  We import that constant from commands.review (its authoritative
  home) so the run-record status can never drift from the skill's own
  exit-code contract. The exit_code field still carries the 0-vs-2
  nuance (clean vs auto-corrected) for telemetry; status answers the
  single question "consumer-safe?".

* **mode = null, user_intent = null.** adversarial is a reviewer with
  no user mode-pick; it is absent from the Family-D user_intent matrix.

* **Single `review` stage, NO halt.** presentation/paper review is
  single-pass (no critic/fix on dual-file output, no halt-gate). The
  record carries one `review` stage. NO cost/token telemetry is
  captured today (the bare `claude -p` review call uses neither
  --output-format json nor stream_progress — only the legacy
  plan/project paths, out of Cycle-3 scope, have sidecars), so the
  review stage records cost=0 / tokens=0. The lifecycle, status
  mapping, dual-path archive, and subrecord wiring are all real;
  cost capture for adversarial is a documented follow-up. deliverable
  = the human-readable review.md.

* **No finalize guard / no `halted`.** adversarial never halts, so
  there is no halted state to guard. record-finalize is unconditional.

Core semantics copied faithfully from the reference: atomic write
(tempfile + os.replace in the same dir), no-clobber run-N allocation,
canonical + per-run archive dual write.

CLI
---
    run_record_emitter.py record-start \\
        --draft-dir <target_draft> [--started-at <ISO>] \\
        [--skill-version <v>]
        → allocate adversarial run-N, write status=running (review
          stage running). Prints "run-N" to stdout.

    run_record_emitter.py record-finalize \\
        --draft-dir <target_draft> --exit-code <N> \\
        [--started-at <ISO>] [--skill-version <v>]
        → terminal write: status from exit_code via the consumer-safe
          set; review stage completed. Prints the archive path
          (audit/adversarial_runs/run-N/run_record.json) to stdout so
          the caller can wire the parent's subrecord pointer.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Version + the consumer-safe exit set come from the skill package. But
# this tool is invoked by the shell as a STANDALONE script via whatever
# `python3` is first on PATH — which is NOT guaranteed to be the venv the
# package is installed in (e.g. a system/anaconda python when the skill
# is pipx-isolated). So make BOTH imports defensive: a telemetry write
# must never crash on an ImportError. When the package isn't importable
# we (a) read __version__ straight from the sibling __init__.py (the
# package root is a known number of parents up from this file), and
# (b) fall back to the documented consumer-safe set.
try:
    from beril_adversarial import __version__ as _skill_version
except Exception:  # pragma: no cover — package not on this python's path
    _skill_version = None

try:
    from beril_adversarial.commands.review import (
        ADVERSARIAL_CONSUMER_SAFE_EXITS,
    )
except Exception:  # pragma: no cover — defensive (package not importable)
    # Mirrors review.py's authoritative definition. Kept in sync by the
    # test that pins rr.ADVERSARIAL_CONSUMER_SAFE_EXITS == (0, 2).
    ADVERSARIAL_CONSUMER_SAFE_EXITS = (0, 2)


def _resolve_skill_version() -> str:
    """Skill version for the run-record. Prefer the imported package
    __version__; if the package wasn't importable, parse it out of the
    sibling __init__.py (this file is at <pkg>/skill/tools/, so the
    package __init__.py is three parents up). 'unknown' as last resort —
    never crash."""
    if _skill_version:
        return _skill_version
    try:
        init_py = Path(__file__).resolve().parents[2] / "__init__.py"
        if init_py.is_file():
            m = re.search(
                r'__version__\s*=\s*["\']([^"\']+)["\']',
                init_py.read_text(encoding="utf-8"),
            )
            if m:
                return m.group(1)
    except OSError:
        pass
    return "unknown"


_SKILL_VERSION = _resolve_skill_version()
_RUN_RECORD_SCHEMA_VERSION = "run-record.v1"
_ADVERSARIAL_SKILL = "adversarial"
_REVIEW_STAGE_ID = "review"


# ---------------------------------------------------------------------------
# Path helpers — adversarial's OWN slots, never the producer's.
# ---------------------------------------------------------------------------

def _audit_dir(draft_dir: Path) -> Path:
    return draft_dir / "audit"


def _canonical_path(draft_dir: Path) -> Path:
    # NOT audit/run_record.json — that belongs to the producer.
    return _audit_dir(draft_dir) / "adversarial_run_record.json"


def _runs_dir(draft_dir: Path) -> Path:
    # NOT audit/runs/ — that belongs to the producer.
    return _audit_dir(draft_dir) / "adversarial_runs"


def _run_archive_dir(draft_dir: Path, run_n: int) -> Path:
    return _runs_dir(draft_dir) / f"run-{run_n}"


def _archive_path(draft_dir: Path, run_n: int) -> Path:
    return _run_archive_dir(draft_dir, run_n) / "run_record.json"


def _next_run_n(runs_dir: Path) -> int:
    if not runs_dir.is_dir():
        return 1
    n = 1
    while (runs_dir / f"run-{n}").is_dir():
        n += 1
        if n > 9999:
            raise RuntimeError(
                f"cannot allocate adversarial run dir under {runs_dir}; "
                f"too many existing rounds"
            )
    return n


# ---------------------------------------------------------------------------
# Time + atomic write (copy-adapted from the reference emitter)
# ---------------------------------------------------------------------------

def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_minus_seconds(iso_ts: str, seconds: float) -> str:
    try:
        dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc,
        )
        return (dt - timedelta(seconds=float(seconds))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (ValueError, TypeError):
        return iso_ts


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _load_existing(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _find_run_n(record: dict | None) -> int | None:
    if record is None:
        return None
    rid = record.get("run_id")
    if not isinstance(rid, str):
        return None
    m = re.match(r"^run-(\d+)$", rid)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Record assembly
# ---------------------------------------------------------------------------

def _refresh_totals(stages: list[dict]) -> dict:
    totals = {
        "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
        "elapsed_seconds": 0.0,
    }
    for s in stages:
        totals["cost_usd"] += float(s.get("cost_usd", 0.0))
        totals["input_tokens"] += int(s.get("input_tokens", 0))
        totals["output_tokens"] += int(s.get("output_tokens", 0))
        totals["cache_read_tokens"] += int(s.get("cache_read_tokens", 0))
        totals["cache_creation_tokens"] += int(
            s.get("cache_creation_tokens", 0))
        totals["elapsed_seconds"] += float(s.get("elapsed_seconds", 0.0))
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return totals


def _models_used(stages: list[dict]) -> list[str]:
    seen: set[str] = set()
    for s in stages:
        m = s.get("model")
        if isinstance(m, str) and m:
            seen.add(m)
    return sorted(seen)


def _rel_if_file(draft_dir: Path, p: Path) -> str | None:
    return str(p.relative_to(draft_dir)) if p.is_file() else None


def _project_artifacts(draft_dir: Path) -> dict:
    """adversarial's deliverable is the human-readable review .md it
    wrote into the target's audit/. user_intent + deliverable_validation
    are null (adversarial is a reviewer — no user mode-pick, no
    deliverable-validation gate of its own)."""
    review_md = _rel_if_file(
        draft_dir, _audit_dir(draft_dir) / "adversarial_review.md")
    return {
        "user_intent": None,
        "deliverable_validation": None,
        "deliverable": review_md,
    }


def _read_sidecar(sidecar_path: Path | None) -> dict:
    """Read the review's per-call metadata sidecar (written by
    stream_progress.py from the stream-json terminal usage event).
    Fields: estimated_cost_usd, input_tokens, output_tokens,
    cache_read_tokens, cache_creation_tokens (omitted when zero),
    model, elapsed_seconds. {} on missing/malformed (NO_STREAM, no
    python3, or the bare-call fallback ran)."""
    if sidecar_path is None or not Path(sidecar_path).is_file():
        return {}
    try:
        data = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "model": data.get("model"),
        "elapsed_seconds": float(data.get("elapsed_seconds", 0) or 0),
        "input_tokens": int(data.get("input_tokens", 0) or 0),
        "output_tokens": int(data.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(data.get("cache_read_tokens", 0) or 0),
        "cache_creation_tokens": int(
            data.get("cache_creation_tokens", 0) or 0),
        "cost_usd": round(float(data.get("estimated_cost_usd", 0.0) or 0.0), 6),
    }


def _review_stage(
    *, status: str, started_at: str, finished_at: str | None,
    telemetry: dict | None = None,
) -> dict:
    """The single `review` stage. Cost/tokens/model come from the
    stream_progress sidecar (`telemetry`) when present — the review
    claude call runs through stream-json capture; absent (NO_STREAM /
    bare-call fallback) it records zeros."""
    t = telemetry or {}
    return {
        "id": _REVIEW_STAGE_ID,
        "status": status,
        "model": t.get("model"),
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": float(t.get("elapsed_seconds", 0.0) or 0.0),
        "input_tokens": int(t.get("input_tokens", 0) or 0),
        "output_tokens": int(t.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(t.get("cache_read_tokens", 0) or 0),
        "cache_creation_tokens": int(t.get("cache_creation_tokens", 0) or 0),
        "cost_usd": round(float(t.get("cost_usd", 0.0) or 0.0), 6),
        "subrecord": None,
    }


def _build_record(
    draft_dir: Path,
    *,
    run_n: int,
    status: str,
    started_at: str,
    finished_at: str | None,
    exit_code: int | None,
    current_stage: str | None,
    stages: list[dict],
    skill_version: str,
) -> dict:
    return {
        "schema_version": _RUN_RECORD_SCHEMA_VERSION,
        "skill": _ADVERSARIAL_SKILL,
        "skill_version": skill_version,
        "run_id": f"run-{run_n}",
        "draft_dir": str(draft_dir),
        "mode": None,  # adversarial is a reviewer; no user mode-pick.
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "current_stage": current_stage,
        "stages": stages,
        "totals": _refresh_totals(stages),
        "models_used": _models_used(stages),
        "artifacts": _project_artifacts(draft_dir),
    }


def _write_canonical_and_archive(
    draft_dir: Path, record: dict, run_n: int,
) -> tuple[Path, Path]:
    """Archive FIRST, canonical SECOND (an interrupted write leaves the
    archive intact + canonical at the prior version). Both in
    adversarial's OWN slots — the producer's audit/run_record.json +
    audit/runs/ are never touched."""
    _audit_dir(draft_dir).mkdir(parents=True, exist_ok=True)
    _runs_dir(draft_dir).mkdir(parents=True, exist_ok=True)
    archive = _archive_path(draft_dir, run_n)
    archive.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(archive, record)
    canonical = _canonical_path(draft_dir)
    _atomic_write_json(canonical, record)
    return canonical, archive


# ---------------------------------------------------------------------------
# Public emitter API
# ---------------------------------------------------------------------------

def record_start(
    draft_dir: Path,
    *,
    started_at: str | None = None,
    skill_version: str | None = None,
) -> int:
    """Allocate adversarial's next run-N (no-clobber, scoped to
    adversarial_runs/), write a status=running record with the review
    stage running. Returns run_n."""
    draft_dir = Path(draft_dir)
    _runs_dir(draft_dir).mkdir(parents=True, exist_ok=True)
    run_n = _next_run_n(_runs_dir(draft_dir))
    started = started_at or _utc_iso_now()
    record = _build_record(
        draft_dir,
        run_n=run_n,
        status="running",
        started_at=started,
        finished_at=None,
        exit_code=None,
        current_stage=_REVIEW_STAGE_ID,
        stages=[_review_stage(
            status="running", started_at=started, finished_at=None)],
        skill_version=skill_version or _SKILL_VERSION,
    )
    _write_canonical_and_archive(draft_dir, record, run_n)
    return run_n


def status_for_exit_code(exit_code: int) -> str:
    """completed iff the review produced a consumer-safe deliverable
    (exit_code in the skill's authoritative consumer-safe set); else
    failed. Keyed off the imported constant — never a hardcoded list."""
    return ("completed"
            if int(exit_code) in ADVERSARIAL_CONSUMER_SAFE_EXITS
            else "failed")


def record_finalize(
    draft_dir: Path,
    *,
    exit_code: int,
    started_at: str | None = None,
    skill_version: str | None = None,
    from_sidecar: Path | None = None,
) -> tuple[Path, Path] | None:
    """Terminal write. status from exit_code via the consumer-safe set;
    the review stage flips to completed; finished_at + exit_code set;
    current_stage cleared. Returns (canonical, archive) — the caller
    uses the archive path to wire the parent's subrecord pointer.

    adversarial never halts, so there is no halted state to guard;
    record-finalize is unconditional. If no record-start ran (defensive),
    bootstrap one so the terminal record is coherent."""
    draft_dir = Path(draft_dir)
    existing = _load_existing(_canonical_path(draft_dir))
    if existing is None:
        record_start(draft_dir, started_at=started_at,
                     skill_version=skill_version)
        existing = _load_existing(_canonical_path(draft_dir))
        if existing is None:
            return None

    run_n = _find_run_n(existing) or _next_run_n(_runs_dir(draft_dir))
    status = status_for_exit_code(exit_code)
    started = existing.get("started_at") or started_at or _utc_iso_now()
    finished = _utc_iso_now()
    telemetry = _read_sidecar(from_sidecar)
    # Review stage started_at: prefer the one record-start stamped; if
    # the sidecar carries real elapsed, back-date from finished so the
    # stage's wall-clock matches the captured duration.
    review_started = started
    prior_stages = existing.get("stages") or []
    if prior_stages and isinstance(prior_stages[0], dict):
        review_started = prior_stages[0].get("started_at") or started
    elapsed = float(telemetry.get("elapsed_seconds", 0.0) or 0.0)
    if elapsed > 0:
        review_started = _iso_minus_seconds(finished, elapsed)
    record = _build_record(
        draft_dir,
        run_n=run_n,
        status=status,
        started_at=started,
        finished_at=finished,
        exit_code=int(exit_code),
        current_stage=None,
        stages=[_review_stage(
            status="completed", started_at=review_started,
            finished_at=finished, telemetry=telemetry)],
        skill_version=existing.get(
            "skill_version", skill_version or _SKILL_VERSION),
    )
    canonical, archive = _write_canonical_and_archive(draft_dir, record, run_n)

    # C1-D telemetry egress: project the persisted record through the strict
    # drop-by-default whitelist and best-effort batch-write ONE JSONL to the
    # shared egress root. UNCONDITIONAL after the canonical write — adversarial
    # never halts (record-finalize is unconditional), so there is NO A1/A2
    # resume/dropped-stage class to be after (unlike the drafting skills).
    # draft_hash is computed from the REVIEWED draft's draft_dir, so it MATCHES
    # the producer's draft_hash → `craft inspect telemetry` shows a draft's
    # full cost INCLUDING its review under one draft_hash (intended).
    # Disabled (CRAFT_TELEMETRY_ROOT=off) → cheap no-op. NEVER raises / slows
    # finalize: the egress fn swallows its own faults, and this wrapper
    # double-guards a vendored-import hiccup.
    #
    # DOUBLE-COUNT NOTE (out of scope for D — flagged): the adversarial→parent
    # cost rollup is still backlog, so the parent pipeline records its
    # `adversarial_review` stage at cost≈0 while adversarial's own record
    # carries the real ~$9.35/review. They are different `(skill, op)` rows, so
    # `craft inspect telemetry` separates them — no double count TODAY. When the
    # rollup lands (the parent stage gets the real cost), reconcile so inspect
    # doesn't sum both for the same review.
    try:
        from beril_adversarial import telemetry as _craft_telemetry
        _craft_telemetry.egress_run_record(
            record, audit_dir=_audit_dir(draft_dir))
    except Exception as _exc:  # noqa: BLE001 — telemetry NEVER perturbs finalize
        print(f"run_record_emitter: telemetry egress skipped "
              f"({type(_exc).__name__}: {_exc}).", file=sys.stderr)

    return canonical, archive


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_draft_dir(raw: str) -> Path | None:
    p = Path(raw).expanduser()
    if not p.is_dir():
        return None
    return p.resolve()


def _cmd_record_start(args) -> int:
    draft = _resolve_draft_dir(args.draft_dir)
    if draft is None:
        print(f"run_record_emitter: draft_dir not found: {args.draft_dir}",
              file=sys.stderr)
        return 1
    run_n = record_start(
        draft, started_at=args.started_at,
        skill_version=args.skill_version or _SKILL_VERSION,
    )
    # Stdout: the allocated run id (callers may capture it).
    print(f"run-{run_n}")
    print(f"run_record_emitter: record-start run-{run_n} → "
          f"{_canonical_path(draft)}", file=sys.stderr)
    return 0


def _cmd_record_finalize(args) -> int:
    draft = _resolve_draft_dir(args.draft_dir)
    if draft is None:
        print(f"run_record_emitter: draft_dir not found: {args.draft_dir}",
              file=sys.stderr)
        return 1
    out = record_finalize(
        draft, exit_code=args.exit_code, started_at=args.started_at,
        skill_version=args.skill_version or _SKILL_VERSION,
        from_sidecar=(Path(args.from_sidecar) if args.from_sidecar else None),
    )
    if out is None:
        print("run_record_emitter: record-finalize could not write",
              file=sys.stderr)
        return 1
    canonical, archive = out
    # Stdout: the archive path (the round) so the caller can wire the
    # parent's stages[].subrecord pointer.
    print(str(archive))
    print(f"run_record_emitter: record-finalize exit_code={args.exit_code}"
          f" → {canonical}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="run_record_emitter",
        description=(
            "Cycle-3 DP1 adversarial run-record.v1 emitter. Writes into "
            "the TARGET draft's audit/ under adversarial's own slots "
            "(adversarial_run_record.json + adversarial_runs/run-N/), "
            "never the producer's audit/run_record.json."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser(
        "record-start",
        help="Write the initial adversarial run record (status=running, "
             "allocates the next adversarial run-N).",
    )
    p_start.add_argument("--draft-dir", required=True)
    p_start.add_argument("--started-at", default=None,
                         help="Review start time, ISO-8601 UTC.")
    p_start.add_argument("--skill-version", default=None)
    p_start.set_defaults(func=_cmd_record_start)

    p_fin = sub.add_parser(
        "record-finalize",
        help="Terminal write. status=completed iff exit_code is "
             "consumer-safe (ADVERSARIAL_CONSUMER_SAFE_EXITS), else "
             "failed. Prints the round's archive path for subrecord "
             "wiring.",
    )
    p_fin.add_argument("--draft-dir", required=True)
    p_fin.add_argument("--exit-code", type=int, required=True)
    p_fin.add_argument("--started-at", default=None)
    p_fin.add_argument("--skill-version", default=None)
    p_fin.add_argument(
        "--from-sidecar", default=None,
        help="Path to the review's stream_progress metadata sidecar "
             "(cost/tokens/model/elapsed from the stream-json terminal "
             "usage event). Folded into the review stage. Omit when the "
             "bare-call fallback ran (review stage stays zero-cost).",
    )
    p_fin.set_defaults(func=_cmd_record_finalize)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
