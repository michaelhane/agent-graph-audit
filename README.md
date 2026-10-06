# agent-graph-audit

Score an AI agent setup on three layers — **harness**, **loop**, and **graph** — and get a percentage with a file:line citation for every check that passes.

> **v0.1 — claim-tier scorer.** It reads text and parses state and workflow files. It does **not** run your loop. A high score means the right artifacts exist, not that the system works in production. Read the score as "how much is written down and wired up", not as a safety grade.

## What it checks

| Layer | Weight | Asks |
|---|---:|---|
| Harness | 30% | Instructions, a real test command, secret hygiene, isolation, tool boundaries, tracing, budgets |
| Loop | 40% | Job claiming, a numeric attempt cap, verification by a command that must pass, fail-closed behaviour, exit on repeated errors, isolated workspaces |
| Graph | 30% | Named nodes, conditional edges, external state, a human gate before merge, the ability to refuse a job, bounded cycles, joins |

Full point tables are in [`references/rubric.md`](references/rubric.md).

### Caps (policy, not measurements)

- Graph credit can't exceed loop + 20. A fancy graph on a weak loop doesn't count.
- Harness under 40 caps the composite at 49.
- No real runner or state file caps the composite at 69. A README that only describes a graph is a claim.

## Install

Tested on Python 3.13. Requires PyYAML, which is only needed to judge workflow files.

```bash
pip install pyyaml
```

As a Claude Code skill, copy this folder into your skills directory. It also works as a plain script. The development files (`CLAUDE.md`, `HANDOFF.md`, `docs/`, `.github/`) aren't needed in an installed copy.

## Run

```bash
python3 scripts/score_setup.py --target /path/to/repo
python3 scripts/score_setup.py --target /path/to/repo --json
```

The report gives the composite, the three layer scores, the next missing check to add, any caps that fired, whether a runner was found, and any folders skipped because they are this skill. Every passing check cites the file and line it matched.

## Tests

```bash
python3 evals/run_evals.py
```

128 cases. Each one is a bypass or bug found in review, for example:

- an empty `state.json` lifting the ceiling
- a workflow comment counted as a job
- `gh pr merge --auto --squash` slipping past the human gate, including when `--auto` sits on a backslash-continued line
- `allow_auto_merge: true` or Renovate's `platformAutomerge` slipping past it
- a committed `.env` key going unnoticed
- `process.env.OPENAI_API_KEY` being flagged as a secret
- a repo inside a `build/` folder scoring 0%
- an installed copy of this skill inflating the score
- "We do not use a worktree" or "unbounded retries" counting as evidence
- `", ".join(parts)` counting as a graph join, or "handle edge cases" as a graph edge

Many cases are the other direction: correct sentences ("one worktree per job", "if tests do not pass, edge back to fix") that a fix must not break.

Run the tests after any change to a pattern.

## Known limits

- It matches text. A determined author can write a README that scores well. The 69 ceiling and the runner checks make that harder, not impossible.
- Any CI job with `runs-on` or `steps` counts as a runner, even a plain lint workflow.
- Runner detection is GitHub Actions only: `.github/workflows/*` and files named `workflow.yml` or `workflow.yaml`. GitLab CI (`.gitlab-ci.yml`), CircleCI (`.circleci/config.yml`) and LangGraph projects (`langgraph.json`) are not recognised. A `state.json` or `jobs.json` record is the way to show a runner for those.
- The human gate is a phrase check. It fails on unnegated auto-merge in any spelling, including inside identifiers (`allow_auto_merge`, `platformAutomerge`, `enablePullRequestAutoMerge`), but a pass does not prove who can merge. Check branch protection yourself.
- Negations other than "no" ("never auto-merge") fail the gate, and so does a setting turned off (`allow_auto_merge: false`). This is deliberate: when unsure, it fails closed. The check's `why` field names the line it found.
- Auto-merge in another sense also fails the gate, for example a library option named `auto_merge` or a `GetAutoMergingPreview` API. That mostly shows up in vendored code; `node_modules` and `.venv` are already skipped.
- `merge ... --auto` is matched per command line. Lines ending in a backslash are joined first. A command split some other way (for example a YAML folded `>` block) is not joined.
- Negation is a short window, not a parser. A negator in the 4 words before a keyword, in the same clause, cancels it ("we do not use a worktree"), and so does "is not used" or "is disabled" right after. It errs closed: "do not reuse a worktree between jobs" also reads as negated. "Worktrees are not shared" passes.
- Graph checks, and the loop's claim, fail-closed and repeated-error checks, match words in docs and config only, not in code comments. Code counts for the graph only through graph-builder calls (`add_node`, `add_conditional_edges`, `add_edge([a, b], c)`, LangGraph style) and numeric bounds. A graph built some other way in code needs a doc or config that describes it.
- Common words in docs can still false-positive (`trace`, `claim`, "ignore" as a verb). Node names need graph context (an arrow, the word node, or backticks), so "fix bugs, ask for review" no longer counts as three nodes.
- The secret check is a pattern check, not a secret scanner. It flags a key name (`api_key`, `secret`, `token`, `password`) assigned a quoted literal of 12+ characters anywhere, or an unquoted value in `.env`, `.env.*`, `*.env` and `.envrc` files. It ignores placeholders (`your_…`, `…_here`, `xxxxxx`, `changeme`), file paths, environment-variable names like `OPENAI_API_KEY`, and keys that describe a secret rather than hold one (`token_type`, `secret_name`, `token_url`). Use a dedicated secret scanner if you need real assurance.
- Folders that are this skill are skipped and listed in the report. A folder counts as this skill if its `SKILL.md` frontmatter has `name: agent-graph-audit` (quoted or not), or if it has `scripts/score_setup.py` and `references/rubric.md`. Installing the skill in a repo therefore doesn't inflate that repo's score. Scoring this folder itself returns 0% with a "Skipped" note.
- Folders in the skip list (`node_modules`, `.git`, `build`, `dist`, `vendor`, `third_party`, `site-packages`, `target`, tool caches, …) and any folder holding `pyvenv.cfg` are never entered. License files are not read. Only folders below the target are checked, so a repo that itself lives inside a `build/` folder still scans. Symlinked files are read; symlinked folders are not followed.

See [`references/failure-modes.md`](references/failure-modes.md) for patterns that should lower your trust in a high score.

## Roadmap

**v0.2: evidence tiers.** A prose mention earns 0.25, config or code earns 0.75, and a lived-in record earns 1.0 (several jobs, timestamps, an attempt above 0, a trace line citing a job_id, and a workflow that references the loop). When this ships, the 69 ceiling goes away.

## License

MIT. See [LICENSE](LICENSE).
