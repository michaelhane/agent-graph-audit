# Handoff: agent-graph-audit

**Last updated:** 2026-10-06
**State:** v0.1 plus review fixes H1–H7. `python3 evals/run_evals.py` gives **106/106** on Python 3.13.16 with PyYAML 6.0.3.

This file is the single source of truth for status. The two documents in `docs/reviews/` are history: they explain *why* each fix exists, but their "open" lists are out of date.

---

## 1. What this is

A Claude Code skill (`SKILL.md`) plus a Python scorer (`scripts/score_setup.py`). It reads a repo's files and scores its agent setup on three layers: harness 30%, loop 40%, graph 30%. Every passing check must cite `file:line`.

It is a **claim-tier** scorer. It matches text and parses state and workflow files; it never runs anything. Policy caps:

- graph credit is at most loop + 20
- harness under 40 caps the composite at 49
- no real runner or state file caps the composite at 69

## 2. Layout

| Path | What |
|---|---|
| `SKILL.md` | Skill instructions Claude follows when using it |
| `scripts/score_setup.py` | The scorer. `--target <dir>`, optional `--json` |
| `evals/run_evals.py` | 106 regression cases. Every one is a bug or bypass found in review, or a guard against over-correcting one |
| `references/rubric.md` | Point table, caps, where each check looks, negation rule |
| `references/failure-modes.md` | When to distrust a high score |
| `README.md` | User-facing docs and known limits |
| `CLAUDE.md` | Working rules for agents in this repo |
| `docs/reviews/` | The two review reports (historical) |
| `.github/workflows/evals.yml` | CI: runs the evals on push and PR |

## 3. Verify

```bash
pip install -r requirements.txt
python3 evals/run_evals.py                       # expect 106/106
python3 scripts/score_setup.py --target .        # expect "Skipped: the target is this skill itself"
```

Scoring this folder returns 0% on purpose (see decision 6).

## 4. Done

| Item | Fix |
|---|---|
| H1 | Installing the skill inside a repo inflated that repo's score (8% → 69%). Folders that are this skill are now skipped, detected by frontmatter `name: agent-graph-audit` (quoted or not) or by the `scripts/score_setup.py` + `references/rubric.md` layout, and listed in the report. |
| H2 | A repo inside a folder named `build/`, `dist/` and so on scored 0%, because the skip list was checked against the full path. One pruned `os.walk` now checks only folders below the target. On a 50k-file `node_modules` it takes 0.06 s (was 0.58 s originally, 2.94 s after the first patch). Symlinked files are read; symlinked folders are not followed. |
| H3 | `.env` files were never read. `.env`, `.env.*`, `*.env` and `.envrc` are now read. |
| H4 | The secret pattern missed JSON keys, `SECRET_KEY`, AWS-style keys and JWTs, and flagged placeholders. Now a quoted literal counts anywhere and an unquoted value only in env files. Placeholders, paths, env-var names (`OPENAI_API_KEY`) and descriptor keys (`token_type`) don't count. No false positive on the whole Python stdlib. |
| H5 | Auto-merge slipped past the human gate in four spellings: `allow_auto_merge`, `platformAutomerge`, `enablePullRequestAutoMerge`, and `--auto` on a `\` continuation line. All four are caught, and the check's `why` cites where. |
| H6 | Negated mentions counted ("we do not use a worktree", "unbounded retries", "no max attempts"). A 4-word clause window now cancels them, and `max attempts` needs a number. |
| H7 | Prose words matched inside code (`", ".join`, `# type: ignore`, license "ANY CLAIM", comments) and in vendored folders. Graph checks and the loop's claim, fail-closed and repeated-error checks now read docs and config only. Code counts for the graph through `add_node`, `add_conditional_edges`, `add_edge([a, b], c)` and numeric bounds. More folders are skipped (vendor, caches, virtual environments by `pyvenv.cfg`), and so are license files. Python stdlib: 69% → 28%. |
| L3 | Dead code (`names_blob`, `file_text`) removed. |
| D1, D2 | Rubric and README claims aligned with the code. |
| D6 | SKILL.md frontmatter keeps only `name` and `description` (`type` and `lifecycle` removed). The `harness-creator` pointer is gone; no other skill is named. |

## 5. Decisions (deliberate; change only on request)

1. **Fail closed when unsure.** A negation in the 4 words before a keyword cancels it, even in "do not reuse a worktree between jobs". "Worktrees are not shared" still passes.
2. **Isolation negators.** "share / single / same" also negate the two isolation checks, unless the clause says per job, each job, or its own.
3. **Auto-merge in any sense fails the gate.** `allow_auto_merge: false`, a library's `auto_merge` option and "never auto-merge" all fail. Only a preceding "no " or "no-" negates. A pass is never proof of who can merge.
4. **Where checks look.** Harness checks, attempt cap and isolated workspace read code too, because a `timeout=`, `git worktree add` or `MAX_PIPE_ATTEMPTS = 20` there is real evidence. Graph word checks and claim, fail-closed and repeated-error read docs and config only.
5. **Node names need graph context:** an arrow, the word node(s), backticks in a doc, or `add_node("…")` in code. The shared `STUFFED` eval fixture was updated to `intake -> triage -> …` for this.
6. **Self-skip.** Any folder that is this skill is skipped, including the target itself. That's why scoring this repo returns 0% with a "Skipped" note.
7. **Secrets.** A quoted literal of 12+ characters counts anywhere; an unquoted value only in env files. Paths, placeholders, env-var names and descriptor keys are ignored. It is a pattern check, not a secret scanner. Citations give `file:line`, never the value.

## 6. Open work, in suggested order

Each item gives a reproduction case to turn into an eval fixture first (it must fail on the current code), then the expected result.

### M1. Real state files are missed (high value)

- A `state.json` over 200 KB (for example 3,000 records, 324 KB) is cut at 200,000 characters before parsing, so it never counts. Expected: `running: true`. Fix: parse state files from the full file.
- `{"jobs": [{"job_id": "j1", "status": "failed", "attempt": 1}]}` isn't recognised. Expected: counts. Fix: accept common wrappers (`jobs`, `records`, `items`) one level down. Consider `state.jsonl`.
- Do **L1** at the same time: a `state.json` of 100,000 nested `[` makes the scorer exit 1 with an uncaught `RecursionError`. Catch `RecursionError`/`ValueError` beside `JSONDecodeError`.

### M3. Common real config scores wrong

False negatives (should pass):

| Fixture | Check |
|---|---|
| `MAX_RETRIES = 3` | attempt cap |
| `@retry(stop=stop_after_attempt(3))` | attempt cap |
| "Run npm run test before merging." | verify command (`npm run lint` already passes) |
| `.claude/settings.json` with `{"permissions": {"allow": [...], "deny": [...]}}` | tool boundary |
| "There is a spend cap of $5 per run." | budget |

False positives (should fail):

| Fixture | Check |
|---|---|
| `pytest>=8.0` in `requirements-dev.txt` | verify command (a dependency line, not a command) |
| "We have a token budget of 50000." | attempt cap (the `budget of \d` alternative) |

### M2. Runner detection

- A LangGraph project (`langgraph.json` with a `graphs` mapping, plus Python using `StateGraph`) never counts as a runner. The `langgraph` path match in `workflow_files` can never pass, because it requires a GitHub-style `jobs:` mapping.
- GitLab (`.gitlab-ci.yml`) and CircleCI (`.circleci/config.yml`) aren't recognised either (from reading the code).
- Decide: either add real checks or remove the dead match, and document "GitHub Actions only".

### Docs, output and hygiene

- **D3:** an empty, 0-byte `CLAUDE.md` passes "instruction file", citing a line 1 that doesn't exist. Should fail.
- **D4:** "external state" says "job id, status, and attempt" but never checks status, and cites only the `job_id` line.
- **D5:** with PyYAML missing, the report says both "no real runner…" (cap line) and "do not read this as a missing runner". Reword one.
- **L2:** `run_evals.py` runs the scorer with `python -I`, which hides `pip install --user` packages. If PyYAML was installed that way, the "real workflow" eval should fail. Use a venv, or `-s -E` instead of `-I`.
- **L4:** `score()` in `run_evals.py` uses `check=True`, so one scorer crash aborts the whole run instead of failing one case.
- **L5:** `verify command`, `instruction file` and `secret ignore` still compute their citation twice (minor speed issue).
- **L6:** the `.gitignore` check matches any `\.env`, including `.envrc` and the un-ignore line `!.env.example`.

**Eval gaps:** no case where the graph cap (`loop + 20`) or the harness-under-40 cap actually changes the result, and no case for the PyYAML-missing path.

### Known limits (accepted for now, documented in README)

- Plain words in docs can still false-positive: `trace`, `claim`, "ignore" as a verb.
- Very large corpora match many words anyway; the Google Cloud SDK (17k files) scores 69%.
- `merge … --auto` split by a YAML folded `>` block isn't joined.
- Roadmap v0.2 "evidence tiers" (prose 0.25, config/code 0.75, lived-in record 1.0) would replace the 69 ceiling. Not started.

## 7. Testing on your own repos

Goal: find false passes and false fails on real setups, and turn each one into a fixture.

```bash
mkdir -p field-tests/output                      # git-ignored
for repo in /path/to/repo-a /path/to/repo-b; do
  name=$(basename "$repo")
  python3 scripts/score_setup.py --target "$repo"        > "field-tests/output/$name.md"
  python3 scripts/score_setup.py --target "$repo" --json > "field-tests/output/$name.json"
done
```

For each repo:

1. For every **passing** check, open the cited `file:line` and decide whether it's real evidence or a false pass.
2. For every **failing** check, decide whether the evidence exists somewhere the scorer didn't look (a false fail).
3. Log each finding in `field-tests/FINDINGS.md`: repo, check, citation, verdict (true pass / false pass / true fail / false fail), one-line reason.
4. For each confirmed false result, write a small **synthetic** fixture that reproduces it, confirm it fails on the current code, then fix it and re-run all repos to see the score changes.

Notes:

- If this repo will be public, keep `FINDINGS.md` generic: no private repo names, paths or content.
- A repo that contains this skill is fine; its folder is skipped and listed in the report.
- The scorer never prints secret values, only `file:line`.
- In a cloud session, the repos you want to test must be available inside that session.
