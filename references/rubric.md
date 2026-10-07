---
description: "Point values and caps for the harness, loop, and graph audit. Read when explaining a score or adjusting a check."
connections: [failure-modes]
---

# Rubric

Scores are evidence scores. A sentence in a doc counts. A diagram that is not executed still counts as a claim, and the report must say so if no runner exists.

## Caps

- Graph credit = min(graph, loop + 20). Policy, not a measurement.
- Harness under 40 caps the composite at 49. Policy.
- No parsed state record and no workflow job with runs-on or steps: composite max 69. Backstop until evidence tiers ship. Workflow means GitHub Actions only (`.github/workflows/*`, `workflow.yml`, `workflow.yaml`); GitLab CI, CircleCI and LangGraph projects are not recognised. A state record needs a non-empty job_id, a status from the known set, and attempt as an int ≥ 0. The record may sit at the top, in a list, or under a `jobs`, `records` or `items` key one level down. Files `state.json`, `jobs.json`, `state.jsonl` and `jobs.jsonl` are read in full.
- Weights: harness 30, loop 40, graph 30. Policy.

## What does not score

- "We use agents" with no claim, verify, or stop.
- A prompt that says "try again" with no numeric cap.
- Auto-merge without a preceding `no` fails the human-gate check, even if a gate phrase is also present. A pass is still not a permission check.
- Secrets assigned as literals. That fails the inline-secret check even if everything else passes.
- A negated mention. "We do not use a worktree", "there is no allowlist", "no max attempts", "unbounded retries" are not evidence. Checks marked *neg* below skip a match when one of the 4 words before it, in the same clause, is a negator (no, not, never, without, nor, cannot, lack, any `n't` word), or when the clause goes on to say "is not used/enabled/set" or "is disabled". For the two isolation checks, "share", "single" and "same" also negate, unless the clause says per job, each job, or its own.

## Where each check looks

- **Docs**: `.md`, `.txt`. **Config**: `.json`, `.yml`, `.yaml`, `.toml`, `.env*`, `.gitignore`. **Code**: `.py`, `.sh`, `.js`, `.ts`, `.mjs`, `Makefile`, `Dockerfile`.
- Graph checks (except external state and human gate) and the loop's claim, fail-closed and repeated-error checks match words in docs and config only. In code those words almost only appear in comments ("non-zero in the result", "LIABLE FOR ANY CLAIM"). Code counts for the graph only through graph-builder calls (`add_node`, `add_conditional_edges`, `add_edge([a, b], c)`) and numeric bounds.
- Every other check reads all three kinds.
- License files (`LICENSE*`, `COPYING*`, `NOTICE*`), vendored code and tool caches (`vendor`, `third_party`, `site-packages`, `target`, `.tox`, `.cache`, …) and any folder holding `pyvenv.cfg` are not read.
- `.claude/worktrees/` is not read, and neither are paths a `.gitignore` ignores, except state files (`state.json`, `jobs.json`, `state.jsonl`, `jobs.jsonl`) and `.claude/settings.json` / `.claude/settings.local.json`. An ignored `.env` is therefore not checked for inline secrets.

## Harness (100)

| Check | Weight | Passes when |
|---|---:|---|
| Instruction file | 15 | `AGENTS.md` or `CLAUDE.md` with at least one non-blank line, or a definition of done |
| Verify command | 15 | A real command: `npm test`, `pytest`, `go test`, `cargo test`, `pnpm test`, `yarn test`, `make test`, `npm run lint`, `npm run typecheck`, `npm run test`. A dependency line (`pytest>=8.0`, `pytest[extras]`, anything in `requirements*.txt`) is not a command. |
| Secret ignore | 10 | A `.gitignore` line that ignores `.env` itself: `.env`, `/.env`, `**/.env`, `.env*` or `*.env`. `.envrc`, `.env.example`, `!` un-ignore lines and comments don't count |
| No inline secrets | 10 | At least one file was scanned and no secret was found. A secret is a key name assigned a quoted literal of 12+ characters, or an unquoted value in a `.env`-style file. Placeholders, paths, env-var names, and descriptor keys like `token_type` don't count |
| Work isolation | 10 | Worktree, branch per, or isolated branch. "one branch" does not pass. *neg*, and "share a single worktree" does not pass |
| Tool boundary | 15 | Allowlist, protected path, cannot merge/push, or a non-empty `allow`/`deny` list in `.claude/settings.json` or `.claude/settings.local.json`. *neg* |
| Trace | 15 | Trace, audit log, tool call, or run log. *neg* |
| Budget | 10 | Timeout, token budget, max minutes, spend cap, or budget. *neg* |

## Loop (100)

| Check | Weight | Award | Passes when |
|---|---:|---:|---|
| Claim | 15 | 15 | Claim or claimed, in progress, lock file, or already taken, in docs or config. *neg* |
| Attempt cap | 20 | 20 | A numeric retry or attempt cap: `max_attempts: 3`, `MAX_RETRIES = 3`, `stop_after_attempt(3)`, `max 3 attempts`, `retry 2`. A "token budget of N" is not an attempt cap. "max attempts" without a number does not pass. *neg* |
| Evidence verify | 20 | 20 | A real test command plus a fail-closed phrase |
| Fail closed | 15 | 15 | Fail closed, exit code, must pass, or non-zero, in docs or config |
| Repeated error exit | 15 | 7 | Same error, same failure, twice, or stuck, in docs or config. Half until a fingerprint exists |
| Isolated workspace | 15 | 15 | Worktree or per job. "dirty tree" does not pass. *neg*, and "share a single worktree" does not pass |

## Graph (100)

| Check | Weight | Passes when |
|---|---:|---|
| Named nodes | 20 | At least three of intake, triage, fix, review, gate, planner, executor, verifier, each on a line with an arrow (`->`, `-->`, `→`, `=>`) or the word node(s), or in backticks in a doc. Or three `add_node("…")` calls in code, any names. "Fix bugs, ask for review, pass the gate" does not pass |
| Conditional edges | 15 | Tests passed, an edge on a line with a condition (if, when, unless, else, otherwise, condition(al), depending, based on, route(d), on failure/pass/…, `==`; not "edge cases", "cutting edge", "edge-cache"), or status ==, in docs or config. *neg*. Or `add_conditional_edges(` in code |
| External state | 20 | `job_id`, `status` and `attempt` all found; all three lines cited |
| Human gate | 15 | A gate phrase, and no unnegated auto-merge (any spelling or word form: automerge, auto merge, auto-merged, auto-merges, auto-merging, also inside identifiers such as allow_auto_merge or platformAutomerge), and no `merge ... --auto` on the same line, where backslash-continued lines count as one |
| Ignore outcome | 10 | Ignore, wontfix, or not fixable in docs (*neg*). In config or code only an outcome value counts: `"ignored"`, `wontfix`, `not_fixable`. `# type: ignore` and a dependabot `ignore:` key do not pass |
| Bounded cycle | 10 | Bounded (not "unbounded"), retry edge, or max attempts, in docs or config (*neg*). Or `recursion_limit` / `max_attempts = N` / `max_retries = N` in code |
| Join | 10 | Join, wait for, or partial diff, in docs or config (*neg*). Or a workflow job with `needs: [a, b]`, or `add_edge([a, b], c)` in code. `", ".join(...)` does not pass |

## Sequence

Do not recommend a larger graph when loop is the weakest layer. Recommend the first missing check in list order on that layer. Ties between layers go to harness, then loop, then graph.
