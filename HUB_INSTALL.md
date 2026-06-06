# beril-adversarial — JupyterHub install runbook

This is the operator runbook for deploying `beril-adversarial` on a KBERDL JupyterHub user environment. It assumes the hub already has BERIL installed at `<BERIL_ROOT>` (with `.claude/skills/`, `projects/`).

For local dev install, see [`README.md`](README.md).

For end-user docs (slash command usage, mode selection, output reading), see [`TUTORIAL.md`](TUTORIAL.md).

For deeper integration / consumer guidance, see [`PLUGIN_GUIDE.md`](PLUGIN_GUIDE.md) and [`CONTRACT.md`](CONTRACT.md).

## Prerequisites

The hub user environment must have:

1. **`pipx`** — for isolated installs of the package CLI.
2. **`claude` CLI** — Anthropic's Claude Code on PATH. The orchestrator invokes `claude -p` per review.
3. **Read access to `BERIL_ROOT/projects/`** — at least one project with `REPORT.md` (and ideally `RESEARCH_PLAN.md`, plus `papers/` or `talks/` subdirectories if you'll be reviewing drafts).
4. **Optional but recommended: `codex` CLI** — for `--reviewer codex` and `--reviewer claude,codex` fusion. Fusion in v0.7.x only applies to legacy `--type project|plan` modes; paper/presentation v3 fusion ships in v0.7.1.
5. **A provider credential in `<BERIL_ROOT>/.env`** for `claude -p` reasoning — `CBORG_API_KEY` (LBL/KBase, via CBORG), `ANTHROPIC_API_KEY` (direct Anthropic), or none (the `subscription` fallback uses ambient Claude Code login). `configure` reads it from `.env`; you don't `export` it.

Verify each:

```bash
which pipx                 # /opt/conda/bin/pipx or similar
which claude               # ~/.local/bin/claude or similar
ls "$BERIL_ROOT/projects/" # at least one project_id
which codex                # optional; ~/.npm-global/bin/codex or similar
```

If `pipx` is missing, install with `python3 -m pip install --user pipx && python3 -m pipx ensurepath`. PEP 668-locked installs may need `--break-system-packages`.

If `claude` is missing, install Claude Code per Anthropic's docs. The skill cannot run reviews without it.

## Install — three steps

### Step 1 — pipx install the package

From any cwd:

```bash
pipx install --force git+https://github.com/kbaseincubator/beril-adversarial-skill.git
```

Alternative URL forms:

- **SSH (requires registered SSH key):**

  ```bash
  pipx install --force git+ssh://git@github.com/kbaseincubator/beril-adversarial-skill.git
  ```

- **Specific version (recommended for production / reproducible deployments):**

  ```bash
  pipx install --force git+https://github.com/kbaseincubator/beril-adversarial-skill.git@v0.7.1
  ```

- **From a wheel file (offline / pinned):**

  ```bash
  pipx install --force /path/to/beril_adversarial_skill-0.7.1-py3-none-any.whl
  ```

Verify the install:

```bash
beril-adversarial --version    # should print 0.7.1 or later
```

If `pipx` warns about PATH, run `pipx ensurepath` once and start a new shell.

### Step 2 — Deploy the skill into BERIL_ROOT

The `install-skill` subcommand copies the bundled `SKILL.md`, slash commands, prompts (paper v3, presentation v3, plan v1, project v1), the orchestrator (`tools/adversarial_review.sh`), and the validator (`tools/validate_presentation_review.py`) into `<BERIL_ROOT>/.claude/skills/beril-adversarial/`. Claude Code auto-discovers skills under `.claude/skills/`, so this is how the slash commands become available.

```bash
cd "$BERIL_ROOT"
beril-adversarial install-skill .
```

Or specify the path explicitly from anywhere:

```bash
beril-adversarial install-skill /path/to/BERIL-research-observatory
```

This will:

- Copy `SKILL.md`, `commands/*.md`, `prompts/*.{v1,v3}.md`, `tools/*.{py,sh}`, `references/*.md` into `.claude/skills/beril-adversarial/`.
- Make `tools/adversarial_review.sh` executable.
- Preserve the `state/` directory verbatim (never overwritten or deleted across re-installs).
- Skip if the destination is up-to-date (idempotent).

Verify:

```bash
ls "$BERIL_ROOT/.claude/skills/beril-adversarial/"
# Expect: SKILL.md, commands/, prompts/, tools/, references/, state/
ls "$BERIL_ROOT/.claude/skills/beril-adversarial/prompts/"
# Expect: adversarial_paper.v3.md, adversarial_presentation.v3.md,
#         adversarial_plan.v1.md, adversarial_project.v1.md
```

If you see `adversarial_paper.v2.md` or `adversarial_presentation.v2.md` in the prompts directory, the install is from a pre-v0.7.0 release. Re-run `pipx install --force` followed by `install-skill` to refresh.

### Step 3 — Configure (bootstrap CRAFT runtime config)

```bash
beril-adversarial configure "$BERIL_ROOT"     # or omit the path to auto-discover
```

`configure` is the one command that makes a deployment ready to run reviews: it wires `claude -p` to a CRAFT-contracted LLM provider and confirms the wiring works *before* your first review. It is no longer just a dependency check. In order, it:

1. **Resolves BERIL_ROOT** — the positional argument, or a discovery walk-up from the current directory if you omit it.
2. **Extends `<BERIL_ROOT>/.env`** with the CRAFT shared-config block + this skill's per-skill marker — additively and idempotently. It never re-declares a key your `.env` already holds, so it is safe to run against the shared BERIL `.env`.
3. **Selects the provider** — `ACTIVE_PROVIDER` ∈ `anthropic | cborg | subscription`. If unset, it is inferred from the keys already in your `.env`: a `CBORG_API_KEY` implies `cborg`, an `ANTHROPIC_API_KEY` implies `anthropic`, neither implies `subscription` (ambient Claude Code login).
4. **Resolves the three model tiers** (`reasoning` / `standard` / `fast`). A tier you pin in `.env` (`MODEL_REASONING` / `MODEL_STANDARD` / `MODEL_FAST`) wins; an unpinned tier is filled by querying the provider's live model list. On a terminal, any tier it can't resolve prompts you to pick from the served candidates; with `--yes` or no TTY, an unresolved tier **fails loud** rather than guessing a default.
5. **Writes the Claude Code settings** Claude Code reads to route `claude -p`: `<BERIL_ROOT>/.claude/settings.json` (provider base URL + the pinned per-tier model ids — safe to commit) and `settings.local.json` (the secret token — gitignored, mode `600`). The local file is added to `.gitignore` automatically.
6. **Runs a validation ping** — a real `claude -p` call against the reasoning tier that asserts the reply is exactly `ok`. This is the load-bearing check: a wrong CBORG model id doesn't error, it answers at exit 0 with a chatty greeting, so an exit-code-only check would false-pass. The ping tests that the config it just resolved actually works.
7. **Stamps** `BERIL_ADVERSARIAL_CONFIGURED_AT` / `_VERSION` into `.env` on success.

Flags:

- `--no-discover` — resolve tiers from `.env` pins only; skip the model-list query (offline, or when you've pinned every tier).
- `--no-ping` — skip the validation ping (offline, or before a token is in place).
- `--yes` / `-y` — non-interactive: never prompt; fail loud on any unresolved tier (for CI / scripted runs).

Exit codes: `0` success · `1` a write/ping failure or user abort · `3` `claude` not on PATH or BERIL_ROOT unresolvable.

**Provider note.** The adversarial reviewer has no image generation and makes no app-internal API calls, but its review *reasoning* runs through `claude -p`, so the provider matters: under `cborg`, `claude -p` authenticates with your CBORG token (written to `settings.local.json`); under `anthropic`, with `ANTHROPIC_API_KEY`; under `subscription`, with your ambient Claude Code login (capped by the monthly Agent SDK credit after 2026-06-15). If a credential the chosen provider needs is missing, `configure` fails loud and names it.

If a check fails, fix it and re-run — `configure` is idempotent. Common cases:

- **`claude` not on PATH (exit 3):** install Claude Code per Anthropic's docs; verify with `which claude`. The skill cannot run reviews without it.
- **An unresolved tier on `--yes` / no TTY:** the provider serves no model for that family, or your pin isn't served. Re-run on a terminal to pick interactively, or pin `MODEL_<TIER>` in `.env`.
- **Ping fails with a non-`ok` reply:** the resolved model answered but not with `ok` — usually a wrong/renamed model id for that tier. Re-pin the tier (interactively, or in `.env`) and re-run.
- **"cannot resolve BERIL_ROOT":** pass it positionally (`beril-adversarial configure /path/to/BERIL-research-observatory`) or `cd` into the deployment first.

## First-run validation

Pick a small / mature draft for the first hub run. The recommended smoke is a paper review against an existing draft:

```bash
cd "$BERIL_ROOT"
beril-adversarial review --type paper \
  projects/<small_project_id>/papers/draft_<N> \
  --beril-root .
```

Expected:

- Wall clock: ~5–10 minutes on Sonnet for a typical paper draft.
- Cost: ~$0.50–$1.00.
- Output: `<draft_dir>/audit/adversarial_review.{md,json}`.

Verify:

1. Exit code 0 (or 2 if the validator auto-corrected a summary count — that's success with a warning, not a failure).
2. Both `adversarial_review.md` and `adversarial_review.json` exist in `<draft_dir>/audit/`.
3. The `.json` parses; `schema_version` is `adversarial-review-paper.v3` (NOT v2 — that means the deployed prompt is stale).
4. The findings array is non-empty (a real paper draft should produce 5–20 findings; zero findings means the LLM under-fired and you should re-run).
5. Exactly one `info`-severity finding with `class: "central_objection"` (the single deck/paper-wide killshot). NO `narrative_weakness` findings — that's the v2 dead name; v3 hard-rejects it.

Quick post-run inspection:

```bash
python3 -c "
import json
audit = 'projects/<small_project_id>/papers/draft_<N>/audit/adversarial_review.json'
d = json.load(open(audit))
print('schema:', d['schema_version'])
print('findings:', len(d['findings']))
print('classes:', sorted(set(f['class'] for f in d['findings'])))
print('central_objection count:', sum(1 for f in d['findings'] if f['class']=='central_objection'))
print('narrative_weakness count (should be 0):', sum(1 for f in d['findings'] if f['class']=='narrative_weakness'))
"
```

If anything fails, see the Troubleshooting section below.

## Verifying the slash command

Inside Claude Code on the hub, the slash command should auto-discover after `install-skill`. Type:

```
/beril-adversarial review --type paper
```

The Claude Code agent should:

1. Verify `beril-adversarial --version` returns 0.7.0+ via the deployed skill subtree.
2. Walk the 4-signal project resolution tree (explicit arg → git branch `projects/<id>` → cwd → ask user).
3. Auto-detect the latest `draft_N` under `papers/` and confirm with the user.
4. Run the orchestrator in the foreground, streaming progress to chat.
5. Surface the output (find counts, severity breakdown, killshot summary).

If the slash command isn't recognized, check that `<BERIL_ROOT>/.claude/skills/beril-adversarial/SKILL.md` exists. Re-run `install-skill` if missing.

If the agent uses the wrong project (e.g., infers from a stale branch), pass the project_id explicitly:

```
/beril-adversarial review --type paper my_project_id
```

## Upgrading

Re-run pipx install with the new version tag:

```bash
pipx install --force git+https://github.com/kbaseincubator/beril-adversarial-skill.git@v0.7.1   # or any later v0.7.x tag
beril-adversarial install-skill "$BERIL_ROOT"   # refresh skill files
beril-adversarial --version                      # confirm
beril-adversarial configure "$BERIL_ROOT"        # re-bootstrap CRAFT config (idempotent)
```

The skill files in `<BERIL_ROOT>/.claude/skills/beril-adversarial/` get refreshed to match the new package version. Existing audit JSONs under `projects/<id>/papers/draft_N/audit/` are forward-compatible — v2 schema docs continue to be readable by v0.7.0+ validators (with a deprecation warning).

### v2 → v3 migration note

If you're upgrading from a pre-v0.7.0 install, the schema renamed `narrative_weakness` → `central_objection` and added `citation_reality` to the presentation schema. Existing v2 audit files remain readable; new runs emit v3. If you have downstream consumer code (e.g., paper-writer's revise loop) that dispatches on the class name, update the dispatch — see [`CONTRACT.md`](CONTRACT.md) §"v0.7.0 migration" at the top.

## Uninstalling

```bash
pipx uninstall beril-adversarial-skill
rm -rf "$BERIL_ROOT/.claude/skills/beril-adversarial"
```

This removes the CLI and the skill files. Existing audit files under `projects/<id>/papers/draft_N/audit/` and `projects/<id>/talks/draft_N/audit/` are NOT touched — those are user-owned artifacts.

## Troubleshooting

### "Error: paper system prompt not found: ...adversarial_paper.v3.md"

The deployed skill is stale (from a pre-v0.7.0 release that didn't have v3 prompts). Refresh:

```bash
pipx install --force git+https://github.com/kbaseincubator/beril-adversarial-skill.git
beril-adversarial install-skill "$BERIL_ROOT"
```

### "BERIL_ROOT does not contain .claude/skills/"

The orchestrator validates BERIL_ROOT at startup. Either:

1. Pass `--beril-root <path>` explicitly with the correct location.
2. Set `$BERIL_ROOT` env var.
3. `cd` into BERIL_ROOT before invoking.

### "beril-adversarial CLI changed in v0.6.0" migration hint

You (or an upstream script like `paper_writer.sh` 0.6.3) invoked the CLI with the pre-v0.6.0 shape (`beril-adversarial --type X <pos>`). The current shape requires the `review` subcommand:

```bash
# Old (pre-v0.6.0):
beril-adversarial --type paper <project_id>

# Current (v0.6.0+):
beril-adversarial review --type paper <draft_dir>
```

Note: the trailing positional changed too — for paper/presentation it's `<draft_dir>` (full path to the per-draft directory), not `<project_id>`. See [`CONTRACT.md`](CONTRACT.md) for full migration guidance.

### "JSON VALIDATION FAILED — non-correctable error(s)"

The LLM produced JSON the validator can't auto-fix. Common causes:

- **Schema violation** (extra fields, wrong types): re-run; usually stochastic.
- **Invalid enum value** (e.g., a class name the v3 schema doesn't accept): re-run; if it persists, the prompt may have drifted.
- **Duplicate finding IDs** (two findings with `id: F005`): re-run.
- **`central_objection` invariant** (more than one info-severity finding, OR `central_objection` with non-info severity): re-run.
- **Dead `narrative_weakness` class in v3** (LLM emitted the v2 name in v3 output): re-run; the prompt instructs against this but occasional drift happens.

The `.md` report may still be useful even when the `.json` fails validation. Re-run usually resolves the issue.

### Auto-correction warning (exit 2)

Not a problem. The validator caught a summary count mismatch in the LLM's output and rewrote the summary from the findings array (which is ground truth). The `.json` file is consumer-safe; the original miscount is preserved at `<output>.original-summary.json` for forensics.

### "claude: command not found" mid-run

The orchestrator failed to invoke `claude -p`. Check `which claude`; if missing, the skill install was OK but Claude Code isn't on PATH at runtime. On JupyterHub, sometimes PATH differs between login shells and Claude Code subprocess shells. Restart Claude Code, or set `PATH` explicitly in `~/.bashrc` / `~/.profile`.

### Reviewer takes >20 minutes for a small draft

Typically network or API rate-limit issue. Check the orchestrator's stderr for retry messages. The orchestrator auto-retries up to 3 times on silent Write failures; if it's still hanging, Ctrl-C and re-run.

### Wrong project_id detected by slash command

The agent inferred the project from your git branch (`projects/<id>`), but you wanted a different project. Pass the project_id (or full draft path) explicitly:

```
/beril-adversarial review --type paper my_project_id
```

Explicit arguments always win over branch / cwd inference.

### Pre-v0.7.0 audit JSONs still readable but warn deprecated

Expected behavior. v2 schema acceptance is preserved for forensic compatibility (so you can re-inspect old `audit/adversarial_review.json` files from v0.6.x runs). New runs emit v3. The deprecation warning will be removed in the release after both consumer skills (paper-writer, presentation-maker) confirm v3 adoption.

## Hub-specific notes

- **No image-gen dependency:** unlike `beril-presentation-maker`, the adversarial reviewer generates no images and makes no app-internal API calls. Its review *reasoning* still runs through `claude -p`, so it uses whatever provider `configure` wired: under `cborg`, the `CBORG_API_KEY` from `settings.local.json`; under `anthropic`, `ANTHROPIC_API_KEY`; under `subscription`, ambient Claude Code login. There is no separate per-skill credential to manage.
- **Per-user storage:** all audit output lives under `<BERIL_ROOT>/projects/<id>/{papers,talks}/draft_<N>/audit/` in the user's BERIL working tree, not in `~/.beril-*` or any user-level state. Multiple users on the same hub stay isolated.
- **Concurrency:** running multiple parallel reviews against the same draft will overwrite output unless you use `--output <basename>` to differentiate. Project / plan modes auto-number output files race-safely.
- **Resumability:** the reviewer is single-pass; it doesn't have a resume mode. If a run fails partway through, simply re-run it.
- **Cost transparency:** each review prints token counts and cost estimate to stderr at the end. No silent costs; nothing else accumulates.

## When to use each subcommand

| Subcommand | Use case |
|---|---|
| `beril-adversarial --version` | Sanity check |
| `beril-adversarial install-skill <BERIL_ROOT>` | One-time per hub deployment + after each pipx upgrade |
| `beril-adversarial configure [<BERIL_ROOT>]` | Bootstrap/refresh CRAFT runtime config (provider, tier models, `settings.json` + validation ping); re-run after `.env` or provider changes |
| `beril-adversarial review --type paper <draft_dir>` | Pre-ship paper audit |
| `beril-adversarial review --type presentation <draft_dir>` | Pre-presentation deck audit |
| `beril-adversarial review --type project <project_id>` | Top-to-bottom project skepticism pass |
| `beril-adversarial review --type plan <project_id>` | Pre-data-collection plan review |
| `beril-adversarial review ... --reviewer claude,codex` | Fusion (legacy `--type plan|project` only in v0.7.x) |
| `beril-adversarial review ... --consolidate` | Synthesize numbered project/plan reviews into FINAL_REVIEW.md |
| `beril-adversarial review ... --output <basename>` | Iteration with named outputs (paper/presentation only) |

End users on the hub will mostly use the slash command (`/beril-adversarial`) inside Claude Code. The CLI subcommands are for operators, scripted workflows (e.g., paper-writer's review-rewrite loop calling `beril-adversarial review --type paper`), and recovery scenarios.
