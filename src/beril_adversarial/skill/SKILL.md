---
name: beril-adversarial
description: |
  Run a harsh, detailed adversarial review of a BERDL analysis project,
  research plan, or paper draft. Supports multi-model fusion (claude +
  codex) and provenance-tracked consolidation across review rounds.
  Use when /berdl-review's lighter pass isn't enough — when the project
  needs a senior-bio-data-scientist level of skepticism, biological-claim
  verification via web search, and explicit data-support checks.
allowed-tools: Bash, Read, Write
user-invocable: true
---

# BERIL Adversarial Reviewer

A harsher parallel to `/berdl-review`. Same artifact graph (README,
RESEARCH_PLAN, REPORT, notebooks, figures, references.md, paper drafts);
different expectations: statistical rigor, hypothesis vetting,
biological-claim verification via WebSearch, scope boundary on data
support, multi-model fusion, and consolidation across rounds with full
revision-history provenance.

The skill ships as a pip-installable Python package
(`beril-adversarial-skill`) plus a Claude Code skill installed at
`<BERIL>/.claude/skills/beril-adversarial/`. The Python layer handles
install + configuration. The review itself is a shell script
(`tools/adversarial_review.sh`) that invokes `claude` or `codex` with
the right system prompt — same pattern as BERIL's `tools/review.sh`.

**Status: v0.1 — first release.** Subject to refinement based on usage.

## Slash commands

### `/beril-adversarial` — run a review

```
/beril-adversarial [<project_id>] [--type plan|project|paper]
                   [--reviewer claude|codex|claude,codex]
                   [--model <model_id>]
                   [--depth quick|standard|deep]
                   [--no-stream] [--no-critic]
                   [--consolidate]
```

**Arguments:**

- `<project_id>` — project directory under `projects/`. Optional if cwd
  is inside `projects/<id>/`.
- `--type plan|project|paper` — what to review. Default `project`.
- `--reviewer claude|codex|claude,codex` — backend. Default `claude`.
  `claude,codex` runs both in parallel and fuses the results.
- `--model <model_id>` — override default model.
- `--depth quick|standard|deep` — thoroughness. Default `standard`.
  `quick` (~1-2m) skips subagents and bio-claim verification — short
  sharp review for fast iteration. `standard` (~5-10m) is the full
  flow. `deep` (~15-25m) expands literature scan, multi-source
  bio-claim verification, sensitivity analyses.
- **(default)** End-of-run summary printed to stderr after the bash
  command returns: tool-call breakdown, subagent count, token usage,
  estimated cost. Programmatically verifies that the Write tool was
  actually invoked — silent-failure detection drives automatic retry
  (up to 3 attempts). Sidecar `<output>.stream.log` preserves raw
  stream-json for post-mortem.
- `--no-stream` — opt out of the stream-json parser. Disables the
  end-of-run summary, programmatic Write verification, retry on
  silent failure, and the sidecar log. Falls back to claude's default
  text output. Useful only for debugging the parser itself or for
  systems where python3 isn't available.
- `--no-critic` — opt out of the post-review compliance critic.
  Default behavior: after the main review writes successfully, a
  separate claude call audits the review against format/discipline
  rules (no Sources sections, strict citation format, no vague
  citation handles, no vague missing-citation suggestions). On
  violations, a targeted fix pass re-runs the original reviewer with
  the violation list to fix in place. Adds 1–3 minutes of latency and
  ~$0.05–0.10 per review but produces substantially more compliant
  output.
- `--consolidate` — skip review; synthesize all numbered reviews of
  matching `--type` into a canonical file with revision history.

**Defaults by type:**

- `plan` — reads RESEARCH_PLAN, README, references.md; writes
  `ADVERSARIAL_PLAN_REVIEW_N.md` at project root.
- `project` (default) — reads all canonical artifacts (README,
  RESEARCH_PLAN, REPORT, prior REVIEW_*.md, notebooks, figures,
  references); writes `ADVERSARIAL_REVIEW_N.md` at project root.
- `paper` — reads `papers/draft{N}.md` (highest N), THROUGHLINE,
  bibliography, citation-map, REPORT, figures; writes
  `papers/draft{N}-review.md` co-located with the draft.

**Tools granted to the reviewer subprocess:**
`Read, Write, Bash, Grep, Glob, WebSearch, Agent`. Richer than
`/berdl-review` so the reviewer can grep notebooks, verify biological
claims via web search, and delegate sub-analysis when needed.

### `/beril-adversarial-configure` — verify environment

Confirm `claude` (required) and `codex` (optional) CLIs are installed
and that WebSearch is reachable. Run once after install, or any time
the toolchain changes.

## Workflow (run a review)

When the user invokes `/beril-adversarial`:

### Step 1 — Resolve project

1. Accept `<project_id>` from the argument, or detect from cwd if
   inside `projects/{id}/`.
2. Validate `projects/{project_id}/` exists.
3. For `--type paper`: validate `projects/{project_id}/papers/` exists
   and contains at least one `draft{N}.md`.

### Step 2 — Invoke the reviewer

Run the shipped shell script:

    bash .claude/skills/beril-adversarial/tools/adversarial_review.sh \
        <project_id> [--type ...] [--reviewer ...] [--model ...]

The script:

- Auto-numbers the output file (race-safe via placeholder).
- Loads the system prompt from `prompts/adversarial_<type>.v1.md`.
- Invokes `claude -p` (or `codex exec`) with the system prompt and a
  short review prompt that points at the project artifacts.
- For `--reviewer claude,codex`: runs both in parallel as
  `*_claude.md` and `*_codex.md` intermediate files, then a third
  `claude -p` with `prompts/fusion.v1.md` produces the unified
  numbered file with dated provenance preserved.

Run from `BERIL_ROOT` (the directory containing `projects/` and
`.claude/`). The script auto-resolves BERIL_ROOT from its own install
path if needed.

### Step 3 — Verify completion

After the script returns:

1. Check the output file was created and is non-empty.
2. Confirm it has YAML frontmatter and a body (the script does this
   too, but a final visual check helps).
3. Print a brief summary: severity counts, biological claims checked,
   any prior-review issues addressed.

### Step 4 — Guidance

Based on the review outcome:

- **No critical issues** — note the project may be ready for `/submit`
  or for paper-writing. Remind the user that adversarial reviews
  PERSIST across rounds and across `/submit` (unlike numbered
  `REVIEW_*.md`, which `/submit` clears).
- **Critical issues** — list them with locations and suggested fixes.
  Offer to help address them. Suggest re-running `/beril-adversarial`
  after fixes to verify.

## Workflow (consolidate)

When the user invokes `/beril-adversarial --consolidate`:

The shell script's consolidation path:

1. Walks all `ADVERSARIAL_REVIEW_*.md` (or `ADVERSARIAL_PLAN_REVIEW_*.md`,
   or `papers/draft*-review.md`) of matching `--type`.
2. Invokes `claude -p` with `prompts/consolidation.v1.md` as system
   prompt, passing all numbered files plus the current artifact
   (REPORT, plan, or latest paper draft).
3. Writes a canonical file:
   - `ADVERSARIAL_REVIEW.md` (project root) for `--type project`
   - `ADVERSARIAL_PLAN_REVIEW.md` for `--type plan`
   - `papers/FINAL_REVIEW.md` for `--type paper`
4. Numbered source files are PRESERVED (audit trail). The canonical
   file's body has a Revision History section that cites each round's
   source file, model, and date inline in square brackets.

## Output artifacts

```
projects/{project_id}/
├── ADVERSARIAL_REVIEW_1.md          # numbered, persists across /submit
├── ADVERSARIAL_REVIEW_2.md
├── ADVERSARIAL_REVIEW_2_claude.md   # intermediate (when --reviewer claude,codex)
├── ADVERSARIAL_REVIEW_2_codex.md
├── ADVERSARIAL_REVIEW_3.md
├── ADVERSARIAL_REVIEW.md            # canonical (after --consolidate)
├── ADVERSARIAL_PLAN_REVIEW_1.md     # for --type plan
├── ADVERSARIAL_PLAN_REVIEW.md       # consolidated plan review
└── papers/
    ├── draft1-review.md             # for --type paper
    ├── draft2-review.md
    └── FINAL_REVIEW.md              # consolidated paper review
```

Numbered files are append-only across the project lifecycle. Only
`/beril-adversarial --consolidate` writes the canonical files;
`/submit` does not touch any `ADVERSARIAL_*` file.

## Reviewer memory (learned-patterns)

The reviewer maintains cross-project meta-memory at
`.claude/skills/beril-adversarial/state/learned-patterns.md` (this
install only — never shipped). Entries record patterns the reviewer
has flagged before that are GENERALIZABLE (not project-specific
gotchas; those go in `docs/pitfalls.md` via the existing
pitfall-capture protocol).

The reviewer reads this file at the start of every review and may
append new entries at the end if it identified a novel general pattern.
Discipline rules in the system prompts keep growth bounded.

## When to use this skill vs. /berdl-review

| Scenario | Use |
| --- | --- |
| Quick feedback during development | `/berdl-review` |
| Pre-publication review of a project | `/beril-adversarial --type project` |
| Plan stage, before data collection / analysis | `/beril-adversarial --type plan` |
| Paper draft from `/beril-paper` | `/beril-adversarial --type paper` |
| Multi-perspective second opinion | `/beril-adversarial --reviewer claude,codex` |
| Consolidating review history into a single canonical doc | `/beril-adversarial --consolidate` |

## Notes

- The system prompts (`prompts/adversarial_{plan,project,paper}.v1.md`,
  `fusion.v1.md`, `consolidation.v1.md`) are the locus of reviewer
  intelligence. They iterate via `.v{N}.md` versioning.
- The rubric reference `references/adversarial-checklist.md` is a
  starting-point list; the system prompts instruct the reviewer not to
  walk it mechanically.
- This skill never modifies project files. All output goes to numbered
  review files or, on consolidation, to canonical review files.
- For provider/model configuration: `claude` and `codex` CLIs carry
  their own configs. This skill does not edit `.env` or hold API keys.

## Pitfall detection

When you encounter errors, unexpected results, or surprising review
outcomes during invocation of this skill, follow the pitfall-capture
protocol. Read `.claude/skills/pitfall-capture/SKILL.md` and follow its
instructions to determine whether the issue belongs in
`docs/pitfalls.md`. Review-meta-patterns belong in `state/learned-patterns.md`
(the reviewer manages that file directly).
