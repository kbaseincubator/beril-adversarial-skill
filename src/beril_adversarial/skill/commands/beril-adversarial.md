---
description: Run a harsh adversarial review of a BERDL project, plan, paper, or presentation. Supports multi-model fusion, depth tiers, and provenance-tracked consolidation.
argument-hint: [<project_id>|<draft_dir>] [--type plan|project|paper|presentation] [--reviewer claude|codex|claude,codex] [--model <model_id>] [--depth quick|standard|deep] [--no-stream] [--no-critic] [--consolidate]
allowed-tools: Bash, Read, Write
---

# /beril-adversarial

Run an adversarial review of the project, plan, paper draft, or
presentation draft. Harsher and more detail-oriented than
`/berdl-review`.

## Mode quick-reference (for the agent — full matrix in SKILL.md)

The four `--type` values have meaningfully different argument
shapes, output paths, and supported flags. Single source of truth
for per-mode behavior is the **Mode selection matrix in SKILL.md**.
Quick reference for branching logic:

| `--type` | Positional arg | Output | JSON schema | Modern v2 architecture? |
|---|---|---|---|---|
| `paper` (v0.6+) | `<draft_dir>` (per-draft directory `papers/draft_N/`) | `<draft_dir>/audit/adversarial_review.{md,json}` | `adversarial-review-paper.v2` | YES — single-pass; rejects `--consolidate` / `--reviewer codex` / `--reviewer claude,codex` |
| `presentation` | `<draft_dir>` (`talks/draft_N/`) | `<draft_dir>/audit/adversarial_review.{md,json}` | `adversarial-review-presentation.v2` | YES — single-pass; same flag rejections |
| `project` (default) | `<project_id>` | `projects/<id>/ADVERSARIAL_REVIEW_N.md` | _none — markdown only_ | NO — legacy; supports fusion, depth, consolidate, compliance critic, citation gate |
| `plan` | `<project_id>` | `projects/<id>/ADVERSARIAL_PLAN_REVIEW_N.md` | _none_ | NO — legacy; same flags as project |

**If the user passes a flag that's unsupported for the chosen mode**
(e.g., `--consolidate` with `--type paper`), the shell script
rejects with a diagnostic. Surface that diagnostic verbatim — don't
try to silently fall back.

**Argument-shape error to watch for:** if the user passes a
`<project_id>` (e.g., `my_project`) with `--type paper` or
`--type presentation`, the script will reject because those modes
expect an absolute path to a `<draft_dir>`. Help the user form the
correct path: `projects/<id>/papers/draft_N/` or
`projects/<id>/talks/draft_N/`.

## Step 1 — Verify the package is installed

Run in a Bash block:

    beril-adversarial --version

If the command is not found, tell the user:

> The `beril-adversarial` package isn't on your PATH. From your BERIL
> root, run the four steps below in order (install package → verify
> CLI loads → configure cross-skill bindings → deploy skill files into
> BERIL):
>
>     cd ~/BERIL-research-observatory
>     pipx install --force git+https://github.com/ArkinLaboratory/beril-adversarial-skill.git \
>       && beril-adversarial --version \
>       && beril-adversarial configure \
>       && beril-adversarial install-skill .
>
> If you have an SSH key registered with GitHub you can also use the
> SSH URL — note the explicit `git@`, which is required:
>
>     pipx install --force git+ssh://git@github.com/ArkinLaboratory/beril-adversarial-skill.git

Stop here if the command is missing. Do not try fallback installs.

## Step 2 — Resolve the project

For `--type plan|project|paper`:

If the user passed `<project_id>` explicitly, use it. Otherwise, check
if cwd is inside `projects/<id>/` and auto-detect. If neither: ask the
user via AskUserQuestion which project to review.

Validate that `projects/<project_id>/` exists. If not, stop with an
error.

For `--type paper`: also confirm `projects/<project_id>/papers/`
contains at least one `draft{N}.md`. If not, tell the user the paper
directory is empty and stop.

For `--type presentation`:

The first positional argument is a `<draft_dir>` (absolute path), not
a project_id. Validate that the path exists and contains
`slide_spec.json` plus `00_throughline.md` plus `02_substories.md`
plus `03_slides/qa_anticipated.json`. The reviewer also requires the
project's `REPORT.md` (resolved as `<draft_dir>/../../REPORT.md`); if
absent, stop with an error — it's the truth source for quantitative
grounding.

If the user did not pass an explicit draft_dir, ask via
AskUserQuestion. Auto-detection by cwd is not supported for
presentation type.

## Step 3 — Invoke the reviewer

**Run the bash command in the FOREGROUND. Do not background it.** A
standard-depth review takes 5–10 minutes and a deep review can take
20+ minutes; that is normal and expected. If the bash tool warns about
a long-running command, wait for it. Backgrounding the call breaks
the user's ability to see the end-of-run summary in the natural
turn-completion flow, and creates ambiguity if the user wants to
abort.

From BERIL_ROOT:

    bash .claude/skills/beril-adversarial/tools/adversarial_review.sh \
        <project_id|draft_dir> \
        --type <type> \
        --reviewer <reviewer> \
        --depth <depth> \
        [--model <model_id>] \
        [--consolidate]

- Omit `--type` if `project` (default).
- Omit `--reviewer` if `claude` (default). Use `codex` for an
  alternative perspective. Use `claude,codex` for parallel reviews
  with fusion. (Both alternatives are unsupported for `--type
  presentation` in v1; the script will reject them.)
- Omit `--depth` if `standard` (default; ~5-10 minutes). Pass `quick`
  (~1-2 minutes, skips subagents) for fast iteration during
  development. Pass `deep` (~15-25 minutes) for thorough
  pre-publication review. (Depth flag is ignored for `--type
  presentation`; v1 is single-depth.)
- Omit `--model` to use the per-reviewer default.
- Pass `--consolidate` to skip review and synthesize numbered reviews
  into a canonical file. (Unsupported for `--type presentation`;
  iteration is owned by presentation-maker's review-rewrite loop.)
- For `--type presentation`: the positional argument is the
  `<draft_dir>` (absolute path), not a project_id. Output is two
  files written into `<draft_dir>/audit/`:
  `adversarial_review.md` (human-readable) + `adversarial_review.json`
  (machine-readable; consumer contract for the
  presentation-maker review-rewrite loop). The compliance critic and
  citation verification gate are skipped (the prompt enforces JSON
  validity itself; the deck has no canonical bibliography to verify).

The script auto-numbers output files race-safely. Multi-reviewer
fusion runs both backends in parallel and produces three artifacts:
intermediate `*_claude.md`, intermediate `*_codex.md`, and the unified
numbered file.

## Step 4 — Verify completion

After the script returns:

For `--type plan|project|paper`:

1. Check the output file exists and is non-empty.
2. Confirm it has YAML frontmatter (`grep -q '^---' <file>`).
3. If validation fails, tell the user and stop.

For `--type paper` and `--type presentation` (both emit dual md+json
output with v2 schemas — see SKILL.md mode matrix):

1. Check that BOTH `<draft_dir>/audit/adversarial_review.md` and
   `<draft_dir>/audit/adversarial_review.json` exist and are
   non-empty.
2. Watch the validator output line in the bash output:
   - `PASS: N {section|slide}-level finding(s), M {manuscript-wide|deck-level} finding(s) ...` — clean run; .json is consumer-safe.
   - `PASS: ...` followed by `AUTO-CORRECTED:` block — validator
     rewrote the LLM's miscounted summary block; sidecar
     `<draft_dir>/audit/adversarial_review.original-summary.json`
     preserves the original. The .json is still consumer-safe;
     surface the auto-correction note to the user.
   - `FAIL:` — non-correctable validation error (schema violation,
     malformed JSON, missing required fields, narrative_weakness
     invariant). The .md may still be useful for human review;
     the .json is unsafe for downstream consumers. Tell the user;
     suggest re-running (most failures are stochastic).
3. JSON schema literal should be `adversarial-review-paper.v2`
   (paper) or `adversarial-review-presentation.v2` (presentation).
   Legacy `adversarial-review-presentation.v1` is accepted by the
   validator with a deprecation warning for forensic reads of older
   audit files only — new runs always emit v2.
4. If either file is missing entirely, tell the user and stop.
   Re-running often resolves stochastic Write-tool failures.

## Step 5 — Present summary

For `--type plan|project|paper`:

Read the output file's frontmatter and Summary section. Present a
brief summary to the user:

- Overall verdict (1–2 sentences from Summary)
- Severity counts: critical / important / suggested
- Biological claims checked / flagged (for project and paper types)
- Churn from prior reviews if applicable: how many issues addressed
  vs. still open
- Pointer to the output file
- **Cumulative run cost** from the review file's `## Run Metadata`
  section at the end (elapsed, tokens, $cost, pipeline labels).
  This is the canonical record. Optionally also quote the per-call
  summary lines that appeared in the bash output (e.g.,
  `Adversarial review: 06:58 · input=... output=... ~$0.163`) for
  per-stage transparency.
- **Compliance critic outcome** — surface this verbatim from the
  bash output. One of:
    - `Compliance critic: PASS` (review compliant on first try)
    - `Compliance critic: N violation(s) — running fix pass...`
      followed by `Compliance critic (post-fix): PASS` (fix worked)
    - `Compliance critic (post-fix): N violation(s) remain.` (fix
      didn't fully land; audit log preserved at `<output>.audit2.md`)

For `--type presentation`:

Read `<draft_dir>/audit/adversarial_review.json` and present:

- Total findings + severity breakdown (P0 / P1 / P2 / info)
- By-class breakdown (throughline, claim_evidence, register_drift,
  qa_softball, substory_arc, missing_slide, unbacked_quantitative,
  narrative_weakness)
- Top 3-5 P0 findings: slide_id + one-line issue
- The single Class 7 narrative_weakness finding (the deck's biggest
  weakness; informational severity)
- Pointer to both output files
- Note that the JSON is the consumer contract for the
  presentation-maker review-rewrite loop (planned v0.3.0); the user
  can act on the .md directly or wait for the loop to operationalize
  fixes

## Step 6 — Guidance

Branch on review outcome:

**No critical issues:**

> The review found no critical issues. The project looks clean from an
> adversarial standpoint. Note that adversarial reviews persist across
> `/submit` cycles — they accumulate as audit trail. Run
> `/beril-adversarial --consolidate` when you want a canonical
> consolidated view across all rounds.

**Critical issues present:**

> The review flagged {N} critical issues:
> 1. {C1 title} — {location}
> 2. {C2 title} — {location}
> ...
>
> Want me to help address these? Re-run `/beril-adversarial` after
> fixes to verify resolution.

**Multi-model fusion run:**

> Fusion reviewed by Claude ({claude-model}) and Codex ({codex-model}).
> {N} issues raised by both; {M} by Claude only; {K} by Codex only.
> {disagreement_count} reviewer disagreements surfaced.

## Step 7 (consolidate path only) — Highlight history

If `--consolidate` was passed:

> Consolidated {N} numbered reviews into canonical
> `<canonical_path>`. Numbered source files preserved as audit trail.
> Persistent open issues: {C} critical, {I} important, {S} suggested.
> Trajectory: {improving | stable | degrading} based on per-round
> severity counts.

## Notes for the agent

- Numbered review files are append-only across the project lifecycle.
  `/submit` does NOT clear them (unlike `REVIEW_*.md`).
- For `--type paper`: the script picks the highest-numbered
  `draft{N}.md` automatically. Output is co-located with the draft as
  `papers/draft{N}-review.md`.
- For `--type presentation`: the user must pass an explicit
  `<draft_dir>` (absolute path). Output overwrites
  `<draft_dir>/audit/adversarial_review.{md,json}` on each run; there
  is no auto-numbering. If the user wants to preserve a prior
  review, they should rename or move the `audit/` directory before
  re-running.
- The shell script handles all error paths (missing project, invalid
  type, script-not-installed, reviewer subprocess failure) and exits
  non-zero with a diagnostic. Surface stderr verbatim if the script
  fails.
- This command never edits project files. All output goes to numbered
  review files or canonical review files in the project directory,
  or (for presentation) to `<draft_dir>/audit/`.
- If WebSearch is unavailable, biological-claim verification will be
  skipped silently; the review will note this in its Summary.
  Presentation reviews do not use WebSearch.

## Pitfall detection

When you encounter errors during this skill — script failures, missing
prompts, unexpected reviewer output — follow the pitfall-capture
protocol. Read `.claude/skills/pitfall-capture/SKILL.md` and follow its
instructions.
