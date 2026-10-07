# Handoff: agent-graph-audit

**Last updated:** 2026-10-06
**State:** v0.2 candidate: v0.1 plus review fixes H1–H7 and the open work below (all items done on branch `finish-v0.2`, pending Micha's review). `python3 evals/run_evals.py` gave **160/160** on Python 3.13.16 with PyYAML 6.0.3 before F1b; after F3 and F7, 177 cases in total (177/177 with the system Python; one skips in a plain venv).

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
| `evals/run_evals.py` | 179 regression cases. Every one is a bug or bypass found in review, or a guard against over-correcting one |
| `references/rubric.md` | Point table, caps, where each check looks, negation rule |
| `references/failure-modes.md` | When to distrust a high score |
| `README.md` | User-facing docs and known limits |
| `CLAUDE.md` | Working rules for agents in this repo |
| `docs/reviews/` | The two review reports (historical) |
| `.github/workflows/evals.yml` | CI: runs the evals on push and PR |

## 3. Verify

```bash
pip install -r requirements.txt
python3 evals/run_evals.py                       # expect 179/179
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
| M1, L1 | State files are parsed from the full file (up to 50M characters), `jobs`/`records`/`items` wrappers one level down count, `state.jsonl`/`jobs.jsonl` are read line by line, and a `RecursionError` or `ValueError` on bad JSON is caught instead of crashing the scorer. |
| M3 | Pass: `MAX_RETRIES = 3`, `stop_after_attempt(3)`, `npm run test`, non-empty `allow`/`deny` in `.claude/settings*.json`, "spend cap". Fail: `pytest>=8.0` dependency lines (and `requirements*.txt`), "token budget of N" as an attempt cap (the `budget of \d` alternative is removed). |
| M2 | Smaller option: the dead `langgraph` path match is removed and the limit is documented (README, rubric): runner detection is GitHub Actions only (`.github/workflows/*`, `workflow.yml`/`.yaml`). GitLab, CircleCI and LangGraph projects are not recognised; a state file is the way to show a runner for them. A `langgraph/*.yml` file with a `jobs` mapping no longer counts. |
| D3 | An empty or whitespace-only `CLAUDE.md`/`AGENTS.md` no longer passes "instruction file". The citation is the first non-blank line. |
| D4 | "External state" now requires `job_id`, `status` and `attempt`, and cites all three lines (it checked only `job_id` and `attempt`, and cited `job_id`). |
| D5 | With PyYAML missing the report no longer contradicts its own cap line: the note now says a workflow file was found but not parsed, so the runner is "unconfirmed" (it used to say "do not read this as a missing runner"). The JSON `runner_note` is unchanged. New evals cover the PyYAML-missing path (workflow file, state file, no workflow). |
| L2 | The evals run the scorer with `-E -P` instead of `-I`, so a PyYAML from `pip install --user` is found. (HANDOFF suggested `-s -E`, but `-s` is the flag that hides the user site, so `-P` is used instead.) |
| L4 | A scorer crash now fails the cases that hit it (`ScorerCrash`) instead of aborting the eval run. `EVAL_SCORER` swaps in another scorer; only the crash check uses it. |
| L5 | `instruction file`, `verify command` and `secret ignore` compute their citation once each in `harness_checks`. |
| L6 | "Secret ignore" needs a `.gitignore` line that ignores `.env` itself (`.env`, `/.env`, `**/.env`, `.env*`, `*.env`). `.envrc`, `.env.example`, `!` un-ignore lines and comments no longer pass. `cite_named` was unused after this and is removed. |
| Eval gaps | Three cases pin the caps: graph credit cut to loop + 20, graph credit left alone inside the limit, and harness under 40 capping the composite at 49 (all with a real state file, so the 69 ceiling can't hide them). Checked by mutation: with the slack and the 49 cap loosened, two of them fail. The PyYAML-missing path was covered under D5. These are coverage cases; they pass on the code before and after, so they could not be shown failing first. |
| L2 venv | In a plain venv (user site off) the L2 eval now reports `skip` instead of failing, because that Python cannot load a user-site package at all. With the system Python it still runs: 154/154; in a plain venv: 153/153 (1 skipped). |
| F1 | Scan scope. `.claude/worktrees/` is never entered, and paths that a `.gitignore` at or below the target ignores are not read (simple matcher: globs, `!`, trailing `/`, anchoring `/`; no global excludes or `.git/info/exclude`). Exceptions, each pinned by a guard case: state files are still read in ignored folders (ignored folders are walked, but only their state files are read), and an ignored `.env` is not read, so it no longer fails "no inline secrets"; a `.env` that is not ignored still fails. Six new cases: 160/160 with the system Python, 159/159 (1 skipped) in a plain venv. Speed is not re-measured yet (F8). |
| F1b | `.claude/settings.json` and `.claude/settings.local.json` are read even when `.gitignore` ignores them, like state files, so "tool boundary" passes and cites them. Nothing else under an ignored `.claude/` is read, and `.claude/worktrees/` stays skipped. Four new cases (pass for each settings file, a guard that `.claude/notes.md` is not cited for human gate, and a citation/`files_scanned` check): 164 cases; the lab's `make test` gives 163/163 (1 skipped). |
| F3 | Of several matching lines, the best one is cited. Files rank state, config, `CLAUDE.md`/`AGENTS.md`, docs, code; a comment (`#`/`//` outside docs, `<!--` in docs), any `.gitignore` line and a Makefile target line are cited only when no other line matches. Pass/fail is unchanged by the ranking; only the citation moves. "Instruction file" cites `CLAUDE.md`/`AGENTS.md` before a definition of done elsewhere. "Verify command" no longer matches `.pytest_cache` (`\bpytest\b`) and never reads `.gitignore`. Three new cases (`.pytest_cache/` fails verify, a guard that a lone comment still counts, and one citation check with six fixtures). |
| F7 | The scorer reconfigures stdout to UTF-8, so on Windows (cp1252 stdout by default) the report's `—` is no longer written as byte `0x97`. One new case runs the scorer with stdout wrapped as cp1252 (what Windows gives without `PYTHONIOENCODING`) and decodes the output as UTF-8 (168 cases together with F3). Tested on Linux with a simulated cp1252 stdout, not on Windows itself. |
| F3b | Only known config files rank as config when choosing a citation: `.claude/settings*.json`, `package.json`, `hooks*.json`, `Makefile` and the non-JSON config suffixes. Any other `.json` is data and ranks last, below docs and code; it still counts when nothing else matches. A permission entry such as `"Bash(git worktree list)"` in a `.json` file is a weak line, cited only as a fallback. Pass/fail is unchanged by the ranking. To make the item's own fixture sentence match, the claim check now also accepts "claimed" (`\bclaim(?:ed)?\b`): "Each job is claimed by one worker." passed nothing before. One new case (two fixtures from the item, three guards): 169 cases; the lab's `make test` gives 168/168 (1 skipped). |
| F2 claim | "Claim" as a noun for a statement no longer passes the claim check: a determiner (a, the, this, our…) plus at most one word before `claim` cancels it ("That is a testable claim.", "the claim"). A claim file, lock, step, node, record, marker or token still counts, and so do "claim a job" and "claimed by". Four new cases (two from the item, two guards): 173 cases; the lab's `make test` gives 172/172 (1 skipped). |
| F2 join | A method call in a doc snippet no longer passes the join check: `join` right after a `.` or right before `(` does not count ("`names.join(', ')`"). "Meet at a join", a `join` node, "wait for", `needs: [a, b]` and `add_edge([a, b], c)` still count. Two new cases (the fixture from the item, and a guard for "The `join` node merges both branches."): 179 cases; the lab's `make test` gives 178/178 (1 skipped). |
| F3c | "Verify command" also accepts a test script run directly: `python`/`python3`/`node`/`bash`/`sh`, optional flags, then a `.py`/`.js`/`.ts`/`.sh` path with `test`, `tests` or `spec` in it at a word start (`python tests/test_gate.py`, `node tests/x.test.js`, `bash tests/run.sh`). By the pattern (no eval case), `python latest.py` or `python setup.py` does not count. Four new cases (the three fixtures from the item, and the guard "We should add tests some day." still fails): 173 cases; the lab's `make test` gives 172/172 (1 skipped). |

## 5. Decisions (deliberate; change only on request)

1. **Fail closed when unsure.** A negation in the 4 words before a keyword cancels it, even in "do not reuse a worktree between jobs". "Worktrees are not shared" still passes.
2. **Isolation negators.** "share / single / same" also negate the two isolation checks, unless the clause says per job, each job, or its own.
3. **Auto-merge in any sense fails the gate.** `allow_auto_merge: false`, a library's `auto_merge` option and "never auto-merge" all fail. Only a preceding "no " or "no-" negates. A pass is never proof of who can merge.
4. **Where checks look.** Harness checks, attempt cap and isolated workspace read code too, because a `timeout=`, `git worktree add` or `MAX_PIPE_ATTEMPTS = 20` there is real evidence. Graph word checks and claim, fail-closed and repeated-error read docs and config only.
5. **Node names need graph context:** an arrow, the word node(s), backticks in a doc, or `add_node("…")` in code. The shared `STUFFED` eval fixture was updated to `intake -> triage -> …` for this.
6. **Self-skip.** Any folder that is this skill is skipped, including the target itself. That's why scoring this repo returns 0% with a "Skipped" note.
7. **Secrets.** A quoted literal of 12+ characters counts anywhere; an unquoted value only in env files. Paths, placeholders, env-var names and descriptor keys are ignored. It is a pattern check, not a secret scanner. Citations give `file:line`, never the value.

8. **Dutch counts.** Evidence written in Dutch counts the same as English, for gate, fail-closed and negation words. (Micha, 2026-10-06)
9. **A config gate counts.** A review-gate config with an ask or confirm mode is human-gate evidence, and stronger than a README sentence. Auto-merge anywhere still fails the gate (decision 3). (Micha, 2026-10-06)

## 6. Open work, in suggested order

Each item gives a reproduction case to turn into an eval fixture first (it must fail on the current code), then the expected result.

Field-test round 1 (2026-10-06): 6 real repos, every citation checked by hand. Of the passing checks, 54 were false passes and 35 true passes; there were 7 false fails. The causes are listed below in suggested order. Repo names stay out of this file.

### F1. Scan scope is too wide: done (see section 4)
- `.claude/worktrees/<name>/` copies of the repo are read, so one sentence gets cited several times. Folders that `.gitignore` lists (caches, browser snapshots, graph caches) are read too. In one large repo the scorer scanned 20,881 files where git tracks 2,539, and the run took 22 minutes.
- Fixture: `.gitignore` with `cache/`, plus `cache/notes.md` containing "human gate" and "a join node". Also `.claude/worktrees/w1/CLAUDE.md`. Expected: neither file is cited, and `files_scanned` counts neither.
- Fix: skip `.claude/worktrees/`, and skip the paths `.gitignore` ignores (simple patterns are enough; no full gitignore engine).
- Exceptions (Micha, 2026-10-06), each pinned by a guard case:
  - State files (`state.json`, `jobs.json`, `state.jsonl`, `jobs.jsonl`) are still read when `.gitignore` lists them. Real loops often ignore their state folder. Fixture: `.gitignore` with `state/` and a valid `state/state.json`. Expected: `running: true`.
  - A `.env*` file that `.gitignore` ignores does not fail "no inline secrets": an ignored env file is the right place for a key. A `.env` that is not ignored is still read and still fails. Fixtures: `.gitignore` with `.env` plus `.env` holding `API_KEY=` and a 20-character value: passes. The same `.env` without that `.gitignore` line: fails.

### F1b. Ignored Claude settings still count: done (see section 4)
Found in a field test after F1: a repo whose `.gitignore` lists `.claude/` lost "tool boundary", because `.claude/settings.json` (a real `permissions.allow` list Claude reads on that machine) is no longer read. Decision (Micha, 2026-10-07): `.claude/settings.json` and `.claude/settings.local.json` are read even when `.gitignore` ignores them, like state files. Nothing else under an ignored `.claude/` is read, and `.claude/worktrees/` stays skipped.
- Fixture: `.gitignore` with `.claude/`, plus `.claude/settings.json` holding `{"permissions": {"allow": ["Read"]}}`. Expected: tool boundary passes and cites `.claude/settings.json`.
- Guard: the same repo with `.claude/notes.md` containing "human gate". Expected: human gate is not cited from `.claude/notes.md`.

### F3. The weakest hit is cited: done (see section 4)
- `.gitignore` containing `.pytest_cache/` passes "verify command" and "evidence verify", even when `pytest` sits in `CLAUDE.md`. Fixture: a `.gitignore` with only `.pytest_cache/`. Expected: verify command fails.
- "Instruction file" cites a plan doc while `CLAUDE.md` exists. Expected: the citation prefers `CLAUDE.md`/`AGENTS.md`.
- "External state" cites `.PHONY: test score status` in a Makefile for the status field, while `state/jobs.json` holds a real `status`. Fixture: a Makefile with `.PHONY: status` plus a `jobs.json` record with `job_id`, `status` and `attempt`. Expected: the status citation points at `jobs.json`.
- "Work isolation" and "isolated workspace" cite a Makefile comment that mentions a worktree, while the README says the fix node makes a fresh worktree per attempt. Expected: a sentence that states the rule wins over an incidental mention.
- General rule for F3: when several lines match, prefer config and state files, then instruction files, then docs. Never cite a comment, an ignore line or a make target when a better line exists.

### F3b. Data files rank as config: done (see section 4)
Found in the field check after F3: the ranking treats any `.json` as config, so a data dump or a code snippet stored as JSON wins over a doc sentence. Seen: "claim" cited from a 4,000-line image-review backup, "budget" from an archived code snippet. A permission entry like `Bash(git -C … worktree list)` in `.claude/settings.local.json` is cited for work isolation, though it only allows a read-only git command.
- Config means known config files: `.claude/settings*.json`, `pyproject.toml`, `package.json`, `Makefile`, `*.yml`/`*.yaml`/`*.toml`/`*.ini`/`*.cfg`, `.github/workflows/*`, hook configs (`hooks*.json`). Other `.json` ranks as data, below docs.
- Fixtures: `backup/data.json` with a `"claim"` string plus `README.md` "Each job is claimed by one worker." Expected: claim cites `README.md:1`. And `.claude/settings.local.json` allowing `Bash(git worktree list)` plus `README.md` "Each job runs in its own worktree." Expected: work isolation cites `README.md:1`.

### F3c. Verify commands written as plain script calls: done (see section 4)
After F3 stopped reading `.gitignore`, one repo lost "verify command" although its `CLAUDE.md` says "Tests: `python tests/test_x.py` and `node tests/test_y.js`". A real test command, but not in the known list.
- Fixture: `CLAUDE.md` with "Tests: `python tests/test_gate.py`". Expected: verify command passes. Also `node tests/x.test.js` and `bash tests/run.sh`.
- Guard: "We should add tests some day." still fails.

### F7. Windows report encoding: done (see section 4)
On Windows, stdout is written as cp1252, so `—` becomes byte `0x97`. Fixture: run the scorer without `PYTHONIOENCODING` and decode stdout as UTF-8. Fix: reconfigure stdout to UTF-8.

### F2. Bare words with another meaning (one job per check)
Each line below is a README sentence that passes today and should fail.
- claim: "That is a testable claim." Done (see section 4).
- conditional edges: "The graph has 3397 edges." and "Edge-cache is on."
- join: "`names.join(', ')`" in a code snippet in a `.md`. Done (see section 4).
- ignore outcome: "Run `git check-ignore`." and "Use `--ignore=tests/slow`."
- budget: "`setTimeout(fn, 100)`" and "Screenshots sometimes time out."
- repeated error exit: "It crashed twice last week."
- trace: "Trace the bug back to the parser."
- bounded cycle: "Cost is bounded per turn."
- attempt cap: `var attempts = 0` (no bound).
- fail closed: "Report a non-zero count."

### F4. Dutch evidence (decision 8)
- human gate: "zonder akkoord", "wacht op akkoord".
- fail closed: "faalt dicht", "stop bij de eerste fout".
- The negation window also needs Dutch negators: niet, geen, nooit, zonder.

### F5. Config gate (decision 9)
A review-gate config such as `hooks/review-gate.json` with `"mode": "ask"` counts as a human gate.

### F8. Speed on large repos
Measure again after F1. Target: under 10 s on 3,000 tracked files.

### F6. Secret check: Dutch key names
`wachtwoord: <literal>` in Markdown is not flagged today. Give the citation only, never the value.

### F9. "claim" as a verb about a statement
Found in the field check after F2 claim: a design doc passes "claim" with "nobody can retroactively claim they created something first". The F2 rule only excludes the noun ("a/the … claim").
- Fixture: `README.md` "Nobody can claim they created it first." Expected: claim fails.
- Guard: `README.md` "Each job is claimed by one worker." still passes.

### F10. "in progress" in plain prose
Found in the same field check: "claim" passes on a blog post's "photos of the tower build in progress", through the `in progress` pattern.
- Fixture: `README.md` "Photos of the build in progress." Expected: claim fails.
- Guard: a state file `jobs.json` with `"status": "in progress"` still passes.

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
