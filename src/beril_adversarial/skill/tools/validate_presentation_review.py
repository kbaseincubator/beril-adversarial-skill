#!/usr/bin/env python3
"""Programmatic post-checker for adversarial_review.json files.

Validates that a presentation reviewer's JSON output conforms to the
``adversarial-review-presentation.v1`` schema and is internally
consistent. Replicates the proven post-checker pattern used by
paper-writer (see memory: feedback_prompt_discipline_needs_post_check.md).

The reviewer's prompt instructs it to recount summary blocks before
emitting; this script enforces that programmatically because prompt-
level discipline alone has been shown to drift in practice.

Exit codes:
  0  pass (all required fields present, counts match, schema literal OK)
  1  fail (validation errors; details on stderr)
  2  warn-only (advisory issues that don't block ship; e.g., zero P0s
     on a 20+ slide deck — possible reviewer under-fire)
  3  cli/usage error

Stdout is one summary line on success, e.g.:
  PASS: 17 slide-level findings, 2 deck-level findings (3 P0, 9 P1, 5 P2, 1 info)

Stderr carries diagnostic detail.

Usage:
    python3 validate_presentation_review.py <path/to/adversarial_review.json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION_LITERAL = "adversarial-review-presentation.v1"

# Severity values that can appear in findings (info is reserved for
# the single Class 7 narrative_weakness finding).
VALID_SEVERITIES = {"P0", "P1", "P2", "info"}

# Class values per SPEC §4.
VALID_CLASSES = {
    "throughline",
    "claim_evidence",
    "register_drift",
    "qa_softball",
    "substory_arc",
    "missing_slide",
    "unbacked_quantitative",
    "narrative_weakness",
}

VALID_CONFIDENCES = {"high", "medium", "low"}

# Fields required on every finding (slide-level and deck-level).
COMMON_REQUIRED_FIELDS = {
    "id",
    "class",
    "severity",
    "confidence",
    "issue",
    "fix_target",
    "fix_hint",
}

# Fields additionally required on slide-level findings.
SLIDE_LEVEL_REQUIRED_FIELDS = {
    "slide_id",
    "slide_position",
    "slide_layout",
    "title_quote",
}

# If the deck has at least this many slides AND the reviewer found
# zero P0 findings, emit a warning (advisory only — exit 2). The
# spec's representative draft_9 has 26 slides + 3 P0s; a zero-P0
# review on a deck this size strongly suggests reviewer under-fire.
ZERO_P0_WARN_SLIDE_THRESHOLD = 20


def validate(doc: dict[str, Any]) -> tuple[list[str], list[str], dict[str, int]]:
    """Validate a parsed JSON document.

    Returns (errors, warnings, summary_stats). Empty errors list ⇒ pass.
    summary_stats has keys 'slide_findings', 'deck_findings', 'p0',
    'p1', 'p2', 'info'.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ----- top-level structure -----
    sv = doc.get("schema_version")
    if sv != SCHEMA_VERSION_LITERAL:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION_LITERAL!r}, got {sv!r}"
        )

    findings = doc.get("findings")
    if not isinstance(findings, list):
        errors.append(
            f"findings must be a list, got {type(findings).__name__}"
        )
        findings = []

    deck_findings = doc.get("deck_level_findings")
    if not isinstance(deck_findings, list):
        errors.append(
            "deck_level_findings must be a list, got "
            f"{type(deck_findings).__name__}"
        )
        deck_findings = []

    summary = doc.get("summary")
    if not isinstance(summary, dict):
        errors.append(f"summary must be a dict, got {type(summary).__name__}")
        summary = {}

    # ----- per-finding validation -----
    severity_counter: Counter[str] = Counter()
    class_counter: Counter[str] = Counter()
    seen_ids: set[str] = set()

    def validate_finding(f: Any, tag: str, require_slide_fields: bool) -> None:
        if not isinstance(f, dict):
            errors.append(f"{tag}: finding must be a dict, got {type(f).__name__}")
            return
        # Required fields
        missing = COMMON_REQUIRED_FIELDS - f.keys()
        if missing:
            errors.append(
                f"{tag} (id={f.get('id', '?')!r}): missing required field(s): "
                f"{sorted(missing)}"
            )
        if require_slide_fields:
            missing_slide = SLIDE_LEVEL_REQUIRED_FIELDS - f.keys()
            if missing_slide:
                errors.append(
                    f"{tag} (id={f.get('id', '?')!r}): missing slide-level "
                    f"field(s): {sorted(missing_slide)}"
                )

        # Field-value validity
        cls = f.get("class")
        if cls is not None and cls not in VALID_CLASSES:
            errors.append(
                f"{tag} (id={f.get('id', '?')!r}): class={cls!r} not in "
                f"{sorted(VALID_CLASSES)}"
            )
        if cls is not None:
            class_counter[cls] += 1

        sev = f.get("severity")
        if sev is not None and sev not in VALID_SEVERITIES:
            errors.append(
                f"{tag} (id={f.get('id', '?')!r}): severity={sev!r} not in "
                f"{sorted(VALID_SEVERITIES)}"
            )
        if sev is not None:
            severity_counter[sev] += 1

        conf = f.get("confidence")
        if conf is not None and conf not in VALID_CONFIDENCES:
            errors.append(
                f"{tag} (id={f.get('id', '?')!r}): confidence={conf!r} not "
                f"in {sorted(VALID_CONFIDENCES)}"
            )

        # ID uniqueness
        fid = f.get("id")
        if isinstance(fid, str):
            if fid in seen_ids:
                errors.append(f"{tag}: duplicate finding id {fid!r}")
            seen_ids.add(fid)

        # narrative_weakness must be severity=info; nothing else should be info
        if cls == "narrative_weakness" and sev != "info":
            errors.append(
                f"{tag} (id={fid!r}): narrative_weakness must have "
                f"severity='info', got {sev!r}"
            )
        if sev == "info" and cls != "narrative_weakness":
            errors.append(
                f"{tag} (id={fid!r}): severity='info' is reserved for "
                f"narrative_weakness, but class={cls!r}"
            )

    for i, f in enumerate(findings):
        validate_finding(f, f"findings[{i}]", require_slide_fields=True)
    for i, f in enumerate(deck_findings):
        validate_finding(f, f"deck_level_findings[{i}]", require_slide_fields=False)

    # ----- summary count consistency -----
    total = len(findings) + len(deck_findings)
    declared_total = summary.get("total_findings")
    if declared_total is not None and declared_total != total:
        errors.append(
            f"summary.total_findings={declared_total} but actual "
            f"findings + deck_level_findings = {total}"
        )

    by_severity = summary.get("by_severity", {})
    if isinstance(by_severity, dict):
        for sev, declared in by_severity.items():
            actual = severity_counter.get(sev, 0)
            if declared != actual:
                errors.append(
                    f"summary.by_severity[{sev!r}]={declared} but actual "
                    f"count = {actual}"
                )
        # Also flag severities present in findings but absent from summary
        for sev, actual in severity_counter.items():
            if sev not in by_severity and actual > 0:
                errors.append(
                    f"summary.by_severity is missing key {sev!r} "
                    f"(actual count = {actual})"
                )

    by_class = summary.get("by_class", {})
    if isinstance(by_class, dict):
        for cls, declared in by_class.items():
            actual = class_counter.get(cls, 0)
            if declared != actual:
                errors.append(
                    f"summary.by_class[{cls!r}]={declared} but actual "
                    f"count = {actual}"
                )
        for cls, actual in class_counter.items():
            if cls not in by_class and actual > 0:
                errors.append(
                    f"summary.by_class is missing key {cls!r} "
                    f"(actual count = {actual})"
                )

    # ----- advisory checks (warnings, not errors) -----
    p0_count = severity_counter.get("P0", 0)
    # Heuristic: if we know how many slides the deck had (the schema
    # doesn't include this directly, but slide_position values give a
    # lower bound), warn on zero P0s above the threshold.
    max_position = 0
    for f in findings:
        if isinstance(f, dict):
            pos = f.get("slide_position")
            if isinstance(pos, int) and pos > max_position:
                max_position = pos
    if p0_count == 0 and max_position >= ZERO_P0_WARN_SLIDE_THRESHOLD:
        warnings.append(
            f"zero P0 findings on a deck with at least {max_position} "
            "slides — possible reviewer under-fire. Spec §9 lists 3 P0s "
            "for draft_9; review the prompt's self-skepticism pass."
        )

    if not findings and not deck_findings:
        warnings.append(
            "reviewer produced zero findings total — almost certainly "
            "did not run the detection protocol. Re-run."
        )

    # narrative_weakness should appear exactly once across both arrays
    narrative_count = class_counter.get("narrative_weakness", 0)
    if narrative_count == 0:
        warnings.append(
            "no narrative_weakness finding emitted — Class 7 is supposed "
            "to produce exactly one. Reviewer skipped the killshot."
        )
    elif narrative_count > 1:
        errors.append(
            f"narrative_weakness should appear exactly once, got "
            f"{narrative_count}"
        )

    summary_stats = {
        "slide_findings": len(findings),
        "deck_findings": len(deck_findings),
        "p0": severity_counter.get("P0", 0),
        "p1": severity_counter.get("P1", 0),
        "p2": severity_counter.get("P2", 0),
        "info": severity_counter.get("info", 0),
    }
    return errors, warnings, summary_stats


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: validate_presentation_review.py <path/to/adversarial_review.json>",
            file=sys.stderr,
        )
        return 3

    path = Path(argv[1])
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 3

    try:
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as e:
        print(f"Error: file is not valid JSON: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: could not read file: {e}", file=sys.stderr)
        return 3

    errors, warnings, stats = validate(doc)

    if errors:
        print(f"FAIL: {len(errors)} validation error(s) in {path.name}", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        if warnings:
            print(f"  Plus {len(warnings)} warning(s):", file=sys.stderr)
            for w in warnings:
                print(f"    - {w}", file=sys.stderr)
        return 1

    msg = (
        f"PASS: {stats['slide_findings']} slide-level finding(s), "
        f"{stats['deck_findings']} deck-level finding(s) "
        f"({stats['p0']} P0, {stats['p1']} P1, {stats['p2']} P2, "
        f"{stats['info']} info)"
    )
    print(msg)

    if warnings:
        print(f"WARN: {len(warnings)} advisory issue(s):", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
