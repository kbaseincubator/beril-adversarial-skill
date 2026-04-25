# beril-adversarial-skill

A harsh, detail-oriented adversarial reviewer for BERDL analysis projects,
research plans, and paper drafts. A parallel to BERIL's `/berdl-review` with
a tougher review prompt, more tools granted to the reviewer subprocess,
biological-claim verification via web search, multi-model fusion (claude
+ codex), and provenance-tracked consolidation across review rounds.

## Status

v0.1 — first release. The review prompts and rubric grow over time;
bump `.v{N}.md` versions when prompts change materially.

## Install

```bash
pipx install git+ssh://git@github.com/ArkinLaboratory/beril-adversarial-skill.git
cd <BERIL_ROOT>
beril-adversarial install-skill .
beril-adversarial configure
```

## Usage

From inside a BERIL deployment with Claude Code running:

```
/beril-adversarial [<project_id>] [--type plan|project|paper]
                   [--reviewer claude|codex|claude,codex]
                   [--model <model_id>]
                   [--consolidate]
```

Defaults:

- `<project_id>` auto-detected from cwd if inside `projects/<id>/`.
- `--type project` reads README, RESEARCH_PLAN, REPORT, prior reviews,
  notebooks, figures, references; writes `ADVERSARIAL_REVIEW_N.md`.
- `--type plan` reads RESEARCH_PLAN; writes `ADVERSARIAL_PLAN_REVIEW_N.md`;
  emphasizes constructive recommendations (missing controls, better
  methods, additional data).
- `--type paper` reads `papers/draft{N}.md`, THROUGHLINE, bibliography;
  writes `papers/draft{N}-review.md`; emphasizes citation-reality
  checks and drift from REPORT.
- `--reviewer claude,codex` runs both backends in parallel and fuses
  with dated provenance.
- `--consolidate` synthesizes all numbered reviews of matching `--type`
  into a canonical file with full revision history; numbered files
  preserved as audit trail.

## Architecture

- **Python package** (`src/beril_adversarial/`) — install + configure
  CLI subcommands. Zero runtime dependencies (stdlib only).
- **Shell script** (`src/beril_adversarial/skill/tools/adversarial_review.sh`)
  — invokes `claude -p` or `codex exec` with the right system prompt.
  Mirrors BERIL's `tools/review.sh` pattern.
- **System prompts** (`src/beril_adversarial/skill/prompts/`) — five
  prompt files: project, plan, paper, fusion, consolidation. Iterable
  via `.v{N}.md` versioning.
- **Rubric** (`src/beril_adversarial/skill/references/adversarial-checklist.md`)
  — single iterable rubric file referenced by all system prompts.

The skill ships as Python `package_data` and is copied into
`<BERIL>/.claude/skills/beril-adversarial/` by `beril-adversarial install-skill`.

## When to use vs. /berdl-review

| Scenario | Use |
| --- | --- |
| Quick feedback during development | `/berdl-review` |
| Pre-publication review of a project | `/beril-adversarial --type project` |
| Plan stage, before data collection | `/beril-adversarial --type plan` |
| Paper draft from `/beril-paper` | `/beril-adversarial --type paper` |
| Multi-perspective second opinion | `/beril-adversarial --reviewer claude,codex` |
| Consolidating review history | `/beril-adversarial --consolidate` |

## Layout

See `LAYOUT.md` for the package + CLI structure spec, including the
canonical review structure, learned-patterns memory model, and
discovery semantics.

## License

MIT — see `LICENSE`.
