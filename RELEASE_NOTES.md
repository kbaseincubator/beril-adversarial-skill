# beril-adversarial-skill — Release Notes

---

## v0.4.0 — 2026-04-28

**New: `--type presentation` mode.**

Adds adversarial review of `beril-presentation-maker` draft directories.
Single-pass reviewer with 7 detection classes, dual output contract,
and a JSON schema designed as the consumer contract for the
presentation-maker review-rewrite loop (planned v0.3.0).

### What's new

- New system prompt: `prompts/adversarial_presentation.v1.md` (1746
  lines, exceeds spec §11's 1500-line guidance). Operationalizes
  spec §4's seven detection classes: throughline integrity,
  claim-evidence load-bearing, tier-language register, Q&A
  anti-strawman, substory→slide arc coherence, missing-slide /
  coverage gaps, deck's biggest narrative weakness. EIGHT worked
  examples walk through real draft_9 slides:
  - register-drift on slide 14 (61.7% / Fisher p=0.031)
  - missing-slide for top-N candidates
  - Q&A softball on slide 22 (Class 4 introductory pattern)
  - substory-arc burial in S3 (climax slide 19 vs 20)
  - throughline filler punchline (S2 vs S3 contrast)
  - narrative_weakness killshot template
  - **caveat-burial detection on slide 18** (Class 2 sub-pattern;
    added post-first-live-run after the reviewer missed the
    weight-sensitivity caveat absence on slide 18)
  - **Q&A "appears defensive but doesn't land" pattern on slide 22**
    (added post-first-live-run after the reviewer emitted "No
    findings" on Q&A; the new example explicitly flags that "No
    findings" verdict as a sign-of-failure trigger to re-do the
    class)
  Self-skepticism pass updated with explicit re-do triggers for
  Q&A under-fire and caveat-burial cross-reference.
- New orchestrator dispatch: `tools/adversarial_review.sh` accepts
  `--type presentation <draft_dir>`. The draft_dir is an absolute
  path (cwd auto-detection is not supported for this type), and the
  script resolves `<draft_dir>/../..` as the project_dir to find
  REPORT.md (the truth source for quantitative grounding).
- Dual output: writes both `<draft_dir>/audit/adversarial_review.md`
  (human-readable) and `<draft_dir>/audit/adversarial_review.json`
  (machine-readable). The .json carries `schema_version:
  "adversarial-review-presentation.v1"` and is the contract surface
  for the presentation-maker review-rewrite loop.
- New programmatic post-checker:
  `tools/validate_presentation_review.py` (replaces the inline shell
  heredoc validator in v0.4.0 alpha). Verifies schema literal,
  required-field presence per finding, severity/class enum
  membership, summary-count consistency against actual array
  contents, finding-id uniqueness, narrative_weakness invariants
  (exactly one, severity=info). Advisory warnings for zero-P0 on a
  20+ slide deck (possible reviewer under-fire) and missing
  narrative_weakness. Replicates paper-writer's post-checker
  pattern (memory: feedback_prompt_discipline_needs_post_check.md).
- Severity grades: `P0` / `P1` / `P2` / `info`. P0 triggers the
  consumer's revise loop; P1 + P2 + info surface in `next_actions`.
- Narrowed tool grant: the reviewer subprocess gets only
  `Read, Write, Grep, Glob`. No WebSearch (would invite citation
  fabrication on a deck with no canonical bibliography to verify).
  No Bash (the work is grep-and-compare across local files).
- 51 new unit tests across two files:
  `tests/unit/test_presentation_review.py` (26 tests — prompt
  content, dispatch validation, documentation, hard-error guards,
  post-iteration worked-example presence) and
  `tests/unit/test_validate_presentation_review.py` (27 tests
  — pass cases, schema validation, required-field checks, summary
  consistency, narrative_weakness invariants, advisory warnings,
  CLI exit codes). Full suite: 106/106 pass.
- Documentation updated: README.md, SKILL.md, slash command doc all
  describe the new mode + the draft_dir argument shape + the
  per-type defaults.

### Skipped for `--type presentation` v1 (vs. paper/project/plan)

- `--consolidate` (presentation iteration is owned by
  presentation-maker's review-rewrite loop, not by this script).
- `--reviewer claude,codex` fusion (single-pass v1; multi-pass
  fusion is v2).
- `--reviewer codex` solo (no programmatic Write detection on
  codex; dual-file output requires verification).
- `--depth quick|deep` (single depth for v1).
- Compliance critic + fix pass (the prompt enforces JSON validity
  itself; running a critic on dual-file output is non-trivial).
- Citation verification gate (no canonical bibliography to verify
  against on a deck).

### Breaking changes

None. All existing `--type plan|project|paper` behavior is
preserved; the `--type` validation just admits a fourth value.

### Acceptance criteria (from SPEC §11)

- [x] `prompts/adversarial_presentation.v1.md` lands; mirrors
  `adversarial_paper.v1.md` shape.
- [x] `tools/adversarial_review.sh` adds `run_presentation_review`
  dispatch.
- [x] `tests/unit/test_presentation_review.py` ≥5 tests, all pass
  (22 tests shipped; full suite 75/75).
- [x] No breaking changes to `--type paper / plan / project` modes.
- [ ] **Live test against draft_9 finds ≥6 of the 8 spec-listed
  issues.** Cost ≤ $1.50 on Sonnet. *(Pending Adam's run; runbook
  in `V0_4_0_PUNCH_LIST.md` Tier D.)*
- [x] `audit/adversarial_review.md` is human-readable;
  `audit/adversarial_review.json` parses + matches schema (the
  prompt + post-run sanity-check enforces this).
- [x] RELEASE_NOTES.md updated with v0.4.0 narrative *(this file)*.

### Architectural decisions

See `V0_4_0_PUNCH_LIST.md` § "Architectural decisions baked into
v0.4.0" for the 10 decisions made (model choice, schema versioning,
no WebSearch, confidence field, single-pass v1, etc.).

---

## v0.3.0 — 2026-04-?? (predates this notes file)

Adds additivity discipline for multi-round reviews.
Carryover-from-Prior-Rounds section comes first; severity counts
reflect new-this-round only; canonical consolidated file is the
live baseline for the next round.

---

## v0.2.0 — 2026-04-?? (predates this notes file)

Adds the programmatic citation verification gate. Every 9-field
citation block in a review is verified against Crossref (DOI) and
NCBI PubMed (PMID); fabricated citations are marked inline with a
`> ⚠️ **CITATION FABRICATED**` blockquote and listed in a Citation
Verification report appended to the review.

---

## v0.1.0 — first release

Three review types (`plan`, `project`, `paper`), multi-model
fusion (`--reviewer claude,codex`), provenance-tracked
consolidation across rounds, depth tiers, compliance critic
+ fix pass, stream-json parser for end-of-run cost summary
+ programmatic Write verification.
