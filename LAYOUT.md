# beril-adversarial-skill — package layout + CLI structure

**Date:** 2026-04-24, last updated 2026-04-25.
**Status:** v0.1 ready for repo init pending live-test signoff.

This document specifies the shape of `ArkinLaboratory/beril-adversarial-skill`.
The skill is modelled on BERIL's `/berdl-review` for the core review-runs-claude
pattern, with packaging modelled on the atlas skill's
pip-installable-with-shipped-skill-data approach.

## Design premise

Adam's manual workflow today: `/synthesize → /berdl-review → {prompt
for adversarial review} → iterate`. The adversarial review is a
harsher reviewer prompt applied to the BERDL artifact graph. Over time
the prompt sharpens. This skill packages that workflow.

Value beyond `/berdl-review`:

- Three review types (plan, project, paper) with distinct system prompts
- Multi-model fusion (`--reviewer claude,codex`) with dated provenance
- `--depth quick|standard|deep` for quick iteration vs. thorough review
- Literature-scan subagent that uses BERIL's MCP tools (PubMed, paper-search)
  to detect prior art, missing methods/datasets, foundational gaps
- Consolidation across rounds with revision-history provenance
- Programmatic Write-tool verification + auto-retry on stochastic
  silent-failure (a real failure mode of `claude -p` with rich tool grants)

## Repository tree

```
ArkinLaboratory/beril-adversarial-skill/
├── pyproject.toml         hatchling build, zero runtime deps
├── README.md, LICENSE, .gitignore, .gitattributes
├── src/beril_adversarial/
│   ├── __init__.py        __version__
│   ├── cli.py             argparse entry: install-skill, configure
│   ├── discovery.py       BERIL_ROOT resolution (atlas pattern)
│   ├── commands/
│   │   ├── install_skill.py    copies skill/ via importlib.resources
│   │   └── configure.py        minimal claude-on-PATH check
│   └── skill/             ships as package_data → .claude/skills/beril-adversarial/
│       ├── SKILL.md
│       ├── commands/      slash command markdowns
│       ├── tools/
│       │   ├── adversarial_review.sh    the heart (~960 lines)
│       │   └── stream_progress.py       Write verification + cost summary
│       ├── prompts/       five system prompts (project / plan / paper /
│       │                  fusion / consolidation), versioned `.v1.md`
│       └── references/    adversarial-checklist.md (single iterable rubric)
└── tests/                 unit + integration; ~29 tests
```

## What ships vs. what runs

**Ships in the package (static, versioned):**
- Shell script `tools/adversarial_review.sh`
- Python parser `tools/stream_progress.py`
- System prompts (5 `.v1.md` files)
- Single rubric reference (`adversarial-checklist.md`)
- SKILL.md and slash command markdowns

**Runs at review time (dynamic):**
- `claude -p` subprocess (or `codex exec`) with the system prompt + a
  short user prompt that points at the project artifacts
- `python3 stream_progress.py` parses claude's `--output-format
  stream-json` for programmatic Write-tool verification, retry control,
  and cost summary

Nothing about the review's content is hardcoded in Python. The Python
layer is install + configure. Review logic = shell + prompt + claude
subprocess.

## CLI

```
beril-adversarial install-skill [<BERIL_ROOT>] [--force]
beril-adversarial configure
```

Exit codes: `0` success / `1` user error / `2` runtime / `3` config.

`install-skill` copies `skill/` into `<BERIL_ROOT>/.claude/skills/beril-adversarial/`
via `importlib.resources`. Preserves install-local `state/` (where the
reviewer's `learned-patterns.md` lives). Sets +x on `tools/*.sh` and
`tools/*.py` after copy.

`configure` is intentionally minimal: just verifies `claude` is on PATH
and reports whether `codex` is also available. WebSearch / MCP / model
auth issues surface at first review run with clear errors; pre-flighting
them adds latency without preventing real failures.

## Slash command

```
/beril-adversarial [<project_id>] [--type plan|project|paper]
                   [--reviewer claude|codex|claude,codex]
                   [--model <model_id>]
                   [--depth quick|standard|deep]
                   [--no-stream]
                   [--consolidate]
```

`<project_id>` auto-detects from cwd if inside `projects/<id>/`, matching
the `/berdl-review` and `/submit` pattern.

**Defaults:**
- `--type project`
- `--reviewer claude`
- `--depth standard` (~5–10 min; `quick` is ~1–2 min, `deep` ~15–25 min)
- Streaming parser ON by default; `--no-stream` to opt out

The slash command markdown explicitly tells the calling agent to run
the bash command **foreground**. Backgrounding it breaks the
end-of-run-summary delivery and creates ambiguity if the user wants
to abort.

## Output routing by `--type`

| `--type` | Reads | Writes (numbered) | Writes (consolidated) |
|---|---|---|---|
| `plan` | RESEARCH_PLAN, README, references.md | `ADVERSARIAL_PLAN_REVIEW_N.md` | `ADVERSARIAL_PLAN_REVIEW.md` |
| `project` (default) | README, RESEARCH_PLAN, REPORT, prior REVIEW_*.md, notebooks, figures, references.md | `ADVERSARIAL_REVIEW_N.md` | `ADVERSARIAL_REVIEW.md` |
| `paper` | `papers/draft{N}.md`, THROUGHLINE, bibliography, REPORT, figures | `papers/draft{N}-review.md` | `papers/FINAL_REVIEW.md` |

For `--reviewer claude,codex`: intermediate `*_claude.md` and `*_codex.md`
files are preserved as audit trail; the fused numbered file is the
primary artifact.

## Path resolution

User prompts pass **absolute paths** for the Write target. An earlier
draft used relative paths (`projects/X/REVIEW.md`) which claude
sometimes resolved against an unexpected base directory, nesting the
review file. Absolute paths bypass whatever heuristic claude uses.

`adversarial_review.sh` derives BERIL_ROOT from its own install path
(symlink-safe via `pwd -P`) and `cd`'s there before invoking claude.

## Stream-json parser

`tools/stream_progress.py` pipes claude's `stream-json` output:

- **Programmatic Write-tool verification.** Detects silent-failure
  (claude produced a chat-response review without invoking Write).
  Exit 2 → shell retries up to 3 attempts with an escalated prompt
  prefix ("ATTEMPT N OF 3 — the previous attempt produced output
  but did not call Write"). Exit 3 (Write on wrong path) →
  non-retryable; surfaces a `mv` recovery hint.
- **End-of-run cost summary** (one line at end of stderr): elapsed,
  tokens, estimated USD cost based on model rate table. Sonnet/Opus/
  Haiku families recognized.
- **Sidecar log** at `<output>.stream.log` preserves raw JSON for
  post-mortem.

What was tried and removed: per-tool-call progress lines. Claude Code's
bash tool batches captured output, so they weren't visible in real time
anyway — just clutter pushed the cost summary out of `tail` view.

## Stochastic-failure retry

The `invoke_claude_with_retry` helper wraps every claude invocation
(single review, fusion claude side, fusion synthesis, consolidation).
On parser exit 2: re-claim placeholder, escalate prompt, retry up to
total 3 attempts. On parser exit 3 or other non-zero: hard-fail with
diagnostic. Codex invocations don't have programmatic Write detection
so they don't retry; codex failures fail fast.

The retry helper is the answer to "why does this sometimes silently
fail?" — claude's tool-vs-respond resolution is stochastic; with rich
tool grants (Read, Write, Bash, Grep, Glob, WebSearch, Agent, ToolSearch)
it occasionally picks "respond" instead of "Write", losing the review.
Detection + retry closes that window.

## System prompts (versioned `.v1.md`)

| File | Lines | Purpose |
|---|---|---|
| `adversarial_project.v1.md` | ~900 | Project review (default). Anti-patterns, citation discipline, depth modes, tool grants, hypothesis vetting structure, biological-claim verification, data-tier scope, learned-patterns protocol. |
| `adversarial_plan.v1.md` | ~430 | Plan review with mandatory literature-scan subagent and "Constructive Recommendations" section (missing controls, better methods, additional data). |
| `adversarial_paper.v1.md` | ~430 | Paper review with citation reality check + supersession scan. |
| `fusion.v1.md` | ~180 | Within-round claude+codex fusion with dated inline provenance (`[file, model, date]` per issue). |
| `consolidation.v1.md` | ~210 | Cross-round canonical review with revision history. |

**Citation discipline (load-bearing convention):** every cited paper
uses a strict 9-field block format (Authors / Year / Title / Venue /
DOI / ID / Studied / Finding / Scope alignment / Assessment). Vague
"Author et al. (Year)" without title is rejected. Self-verification
rule mandates re-reading every citation block before finalizing.

**Anti-patterns section** in project/plan/paper prompts: explicitly
calls out manufactured-doubt (flagging confounds that don't apply to
the project's operational question), plausibility-as-evidence (sounds
right but no paper named), concept-pattern matching (recognizing "this
looks like X" without verifying X applies). Worked example: a project
measuring growth on medium M, reporting 55.1% no-growth — flagging
"medium might be suboptimal" is manufactured doubt because medium IS
the experimental condition.

## Reviewer memory (learned-patterns)

`<BERIL_ROOT>/.claude/skills/beril-adversarial/state/learned-patterns.md`

Cross-project meta-memory of review patterns the reviewer has flagged
before. Different from BERIL's `docs/pitfalls.md`: that file holds
project-specific gotchas; this file holds review-meta-patterns
("projects often report p-values without effect sizes" etc.).

The reviewer reads it at the start of every review and may append at
the end if a novel generalizable pattern was identified. Discipline
enforced by the system prompt: don't append for one-offs, don't
duplicate existing entries (Grep first), don't put project-specific
gotchas here (those belong in `docs/pitfalls.md`).

Install-local; never shipped.

## BERIL_ROOT discovery

`discovery.py` resolves BERIL_ROOT with this priority:

1. `--beril-root <path>` flag
2. `BERIL_ROOT` environment variable
3. Walk up from cwd looking for `.env` + `.claude/skills/` + at least
   one BERIL-core skill directory (`submit/`, `berdl/`, or
   `suggest-research/`)
4. Fail loud with a diagnostic naming which marker failed

Tiebreaker signals (boost confidence): directory name matches
`/BERIL[-_]/i`, `.env.example` contains `KBASE_AUTH_TOKEN`,
`DIRECTORY_STRUCTURE.md` exists.

The shell script's BERIL_ROOT derivation is independent and uses
script-relative path math: tools/ → beril-adversarial/ → skills/ →
.claude/ → BERIL_ROOT, with `pwd -P` for symlink-safety.

## Cross-platform

Python 3.10+. `pathlib.Path` everywhere; no string concatenation for
paths. Bash 3.2-compatible (macOS default) — confirmed by `bash -n`
syntax check. `.gitattributes` enforces LF line endings on
`.sh`/`.py`/`.yaml`/`.toml`/`.md`. Windows users run under WSL or
Git Bash; PowerShell parity is not promised.

## Tests

29 tests across `tests/unit/` and `tests/integration/`:

- `test_discovery.py` (17 tests): explicit-path resolution, env var,
  walk-up, marker checks, derived paths
- `test_install_skill.py` (5 integration tests): full-tree install,
  executable bit on shipped scripts, state preservation across
  reinstall, --force overwrite, fail-on-invalid-root
- `test_stream_progress.py` (7 tests): exit codes 0/2/3, substring-match
  guard regression, parse error tolerance, multiple event-shape detection

Live-LLM tests are not included; they'd cost real money to run in CI
and are brittle. The fixture project under `tests/integration/conftest.py`
is ready for them when needed.

## Deliverables this document blocks

- Repo init: `gh repo create ArkinLaboratory/beril-adversarial-skill --private --clone`
  + initial commit + tag `v0.1.0` + push.
- After signoff from live tests, this LAYOUT becomes the seed
  README/architecture page in the repo's documentation.

## Open questions for Adam (when revisiting)

1. **CI:** run unit tests + shell `bash -n` check on every PR? Currently
   no CI config shipped.
2. **Live integration tests:** worth setting up a periodic real-claude
   smoke test? Costs real money but catches real regressions.
3. **Multi-deployment vocab learned-patterns sync:** if multiple BERIL
   installs use the skill, do we want a way to share learned-patterns?
   (Atlas's contrib mechanism exists but is overkill for this.)
4. **Prompt versioning beyond v1:** when system prompts change
   materially, bump `.v2.md`. The shell script currently hardcodes
   `.v1.md`; a future flag could let users pin a specific version.
