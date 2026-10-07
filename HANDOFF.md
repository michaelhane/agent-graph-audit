# Handoff: agent-graph-audit

**Last updated:** 2026-10-07
**State:** v0.2 candidate: v0.1 plus review fixes H1–H7 and the open work below (all items done on branch `finish-v0.2`, pending Micha's review). `python3 evals/run_evals.py` gave **160/160** on Python 3.13.16 with PyYAML 6.0.3 before F1b; now 257 cases in total (one skips in a plain venv; the lab's `make test` gives 256/256 with 1 skipped).

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
| `evals/run_evals.py` | 257 regression cases. Every one is a bug or bypass found in review, or a guard against over-correcting one |
| `references/rubric.md` | Point table, caps, where each check looks, negation rule |
| `references/failure-modes.md` | When to distrust a high score |
| `README.md` | User-facing docs and known limits |
| `CLAUDE.md` | Working rules for agents in this repo |
| `docs/reviews/` | The two review reports (historical) |
| `.github/workflows/evals.yml` | CI: runs the evals on push and PR |

## 3. Verify

```bash
pip install -r requirements.txt
python3 evals/run_evals.py                       # expect 257/257
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
| F2 conditional edges | The word "edge(s)" passes "conditional edges" only on a line that also has a condition: if, when, unless, else, otherwise, condition(s)/conditional(ly), depending, based on, route/routes/routed/routing, "on pass/fail/failure/success/error/reject(ion)/approval", or `==`. A hyphen compound ("Edge-cache") is not an edge. "Tests passed", "status ==" and `add_conditional_edges(` are unchanged. Four new cases (the two fixtures from the item, and two guards: "On failure, the edge goes back to fix." and "Edges from review are routed by the job status." still pass): 181 cases; the lab's `make test` gives 180/180 (1 skipped). |
| F2 ignore outcome | A command or flag in a doc no longer passes the ignore outcome check: `ignore` right after a `-` or a word character, or right before `-` or `=`, does not count ("Run `git check-ignore`.", "Use `--ignore=tests/slow`."). "Triage can ignore a job that is out of scope." still counts. Three new cases (the two fixtures from the item, and that guard): 186 cases; the lab's `make test` gives 185/185 (1 skipped). |
| F2 budget | `timeout` right after a letter no longer passes the budget check, so a timer call such as `setTimeout(fn, 100)` (or `clearTimeout`) in a doc snippet does not count. `timeout-minutes`, `AGENT_TIMEOUT`, `timeout=` and "a timeout of 30 minutes" still count. "Screenshots sometimes time out." already failed (the pattern needs the single word `timeout`); its case is a guard that passed before the fix. Five new cases (the two fixtures from the item, and three guards): 188 cases; the lab's `make test` gives 187/187 (1 skipped). |
| F2 repeated error exit | `twice` passes the repeated error exit check only on a line that also stops or hands off: stop, exit, halt, abort, end(s), escalate, give up, park or blocked ("It crashed twice last week." no longer counts). "Same error", "same failure" and "stuck" are unchanged. Four new cases (the fixture from the item, and three guards: "If a check fails twice in a row, the job stops.", "Escalate to a human when a fix fails twice." and "The same error on two attempts ends the job." still pass): 195 cases; the lab's `make test` gives 194/194 (1 skipped). |
| F2 trace | `trace` as a debugging verb no longer passes the trace check: `trace` directly before a determiner or pronoun (the, a, an, this, that, it, its, them, their, our, your…) or before `back`/`down` does not count ("Trace the bug back to the parser."). "Each run writes a trace to runs/." and "Trace files live in traces/." still count, and so do audit log, tool call and run log. Three new cases (the fixture from the item, and those two guards): 194 cases; the lab's `make test` gives 193/193 (1 skipped). |
| F2 bounded cycle | "Bounded" no longer passes the bounded cycle check when the line says something other than a cycle is bounded: in "X is/are/was/were/stays/remains [one word] bounded", X must be a loop, cycle, retry/retries, attempt, iteration, round, edge or recursion ("Cost is bounded per turn." and "Memory is strictly bounded." no longer count). A bare "bounded" with no subject, "bounded by max_attempts", "retry edge" and "max attempts" are unchanged. Four new cases (the fixture from the item, "Memory is strictly bounded.", and two guards: "The fix loop is bounded at 3 rounds." and "Retries are always bounded per job." still pass): 199 cases; the lab's `make test` gives 198/198 (1 skipped). |
| F2 attempt cap | A counter that starts at 0 no longer passes the attempt cap check: in the `attempt(s)` followed by `:`, `=` or `<` form, the number may not be `0` ("`var attempts = 0`"). `while (attempts < 3)` and `attempts=3` as an argument still count, and so do `max_attempts`, `MAX_RETRIES = 3` and `stop_after_attempt(3)`. By the pattern (no eval case), a counter that starts at 1 (`attempts = 1`) still passes. Three new cases (the fixture from the item, and those two guards): 201 cases; the lab's `make test` gives 200/200 (1 skipped). |
| F2 fail closed | `non-zero` passes the fail closed check only on a line that also says exit, return, status, code, fail/failure, abort or stop ("Report a non-zero count." no longer counts). "Exits non-zero", "a non-zero status stops the job", "fail closed", "exit code" and "must pass" are unchanged. Three new cases (the fixture from the item, and two guards: "The verify step exits non-zero on any failure." and "A non-zero status stops the job." still pass): 205 cases; the lab's `make test` gives 204/204 (1 skipped). |
| F4 | Dutch evidence (decision 8). Human gate also accepts "zonder akkoord" and "wacht/wachten op akkoord"; fail closed also accepts "faalt dicht" and "stop/stopt/stoppen bij de eerste fout". The negation window also has the Dutch negators niet, geen, nooit and zonder, so "We gebruiken geen worktree." and "Agents draaien zonder timeout." no longer count. Auto-merge still fails a Dutch gate (decision 3). Only negators *before* a keyword are Dutch; the after-the-match form ("wordt niet gebruikt") is English only. Ten new cases (eight fixtures from the item, and two guards: "Elke job krijgt een eigen worktree." still passes, and "zonder akkoord" next to auto-merge still fails the gate): 218 cases; the lab's `make test` gives 217/217 (1 skipped). |
| F5 | A review-gate config counts as a human gate (decision 9): a config file (not a doc or code) whose name has `gate` or `review`, such as `hooks/review-gate.json` or `config/review-gate.yml`, with `mode` set to `ask` or `confirm`. It is cited before a gate phrase, because it is stronger evidence than a README sentence. Auto-merge anywhere still fails the gate (decision 3). Six new cases (the two fixtures, three guards: `"mode": "auto"` is no gate, `"mode": "ask"` in an unrelated `editor.json` is no gate, and a config gate next to auto-merge still fails; and a citation check that the config wins over a README gate): 224 cases; the lab's `make test` gives 223/223 (1 skipped). |
| F8 | Speed. On a synthetic repo of 3,000 files (200 lines each, almost no evidence, so every check reads every line) the scorer took 31.7 s; now about 6 s (5.8 s for `report()` in-process, measured in the lab's venv, Python 3.12). Almost all the time was per-line regex calls in Python. Each file is now joined once (lines separated by `"\x00\n"`), and `best_cite` tries a file's lines only when the whole-file text matches the pattern (with `re.M`). The `"\x00"` keeps a lookahead at a line end from seeing the next line, so any line that matches alone also matches in the joined text. Patterns given to `best_cite` may not use `$`. For speed, the whole-file search drops a pattern's leading `\b` and lookbehinds (only widens it), and on all-ASCII files searches the lowercased text case-sensitively (same result as `re.I` when the pattern has no uppercase literal; other files and patterns keep `re.I`). `secret_hit`, `node_names` and `auto_merge_cite` skip files without their key word, and `file_rank`/`file_kind` are cached. Pass/fail and citations are unchanged: the per-line check is the same as before. Two new cases: the timing case (3,000 files under 10 s, with matches at lines 120 and 150 of a large file and an "edge" / "computing" line break still cited at their own line), and a guard that an uppercase keyword in ASCII text and a keyword in a non-ASCII file are still cited. Both guards passed before the fix; only the timing part failed. 220 cases; the lab's `make test` gives 219/219 (1 skipped). Not measured on a real 3,000-file repo. |
| F6 | Dutch key names (decision 8). The secret check also takes `api_sleutel` (`api-sleutel`, `apisleutel`), `wachtwoord` and `geheim` as key words, from one shared `SECRET_WORDS` pattern that both the key regex and the F8 file prefilter use. The rules of decision 7 are unchanged: a quoted literal counts anywhere, an unquoted value only in env files, and the citation is `file:line`, never the value. So that the new key words don't flag Dutch placeholders, `jouw_…`/`jouw-…` and `…_hier`/`…-hier` count as placeholders, like `your_…` and `…_here`. `geheime…` is not `geheim` (a letter after the key word still cancels it). Nine new cases (three fixtures: `wachtwoord: "…"` in Markdown, `api_sleutel` in JSON, `APP_GEHEIM=` in `.env`; five guards: a Dutch placeholder, a path, an env-var name, an unquoted value in prose, and `geheimeTaal`; and a check that the Markdown case cites `README.md:3` and the value appears in neither the JSON nor the Markdown report): 235 cases; the lab's `make test` gives 234/234 (1 skipped). |
| F9 | "Claim" as a verb about a statement no longer passes the claim check: `claim`/`claimed` directly followed by a subject pronoun (they, he, she, we, I, you), optionally after "that", or by "to be"/"to have" does not count ("Nobody can claim they created it first."). "Claim a job", "claim it" and "claimed by one worker" still count. By the pattern (no eval case), "claims"/"claiming" never matched the claim check, and "claim that X" with a noun subject ("claim that the cache is fresh") still passes. Two new cases (the fixture from the item, and the guard "Each job is claimed by one worker."; the guard passed before the fix): 228 cases; the lab's `make test` gives 227/227 (1 skipped). |
| F10 | "In progress" in plain prose no longer passes the claim check: it counts only as a quoted value (`"in progress"`, `'in progress'`, `` `in progress` ``) or on a line that also says status, state, mark(s/ed), set(s), move(s/d) or flag(s/ged) ("Photos of the build in progress." no longer counts). Claim, lock file and already taken are unchanged. Three new cases (the fixture from the item, and two guards that passed before the fix: `"status": "in progress"` in `jobs.json`, and "A worker marks the job in progress before it starts."): 240 cases; the lab's `make test` gives 239/239 (1 skipped). |
| F11 | `status ==` passes the conditional edges check only when the value is not a number: `status ==` followed by a digit is an HTTP or exit-code check (`if resp.status == 200:`, `assert status == 401`), not a route. "If status == failed, go back to fix." still counts. A number directly before "edge(s)" is a count and never counts, even next to a condition word ("Rebuilt: 290 nodes, 294 edges when the hook fired."). Five new cases (the three fixtures from the item, and two guards: "If status == failed, the edge goes back to fix." and the same line without the word edge still pass; both guards passed before the fix): 242 cases; the lab's `make test` gives 241/241 (1 skipped). |
| F12 | "Join" as becoming a member no longer passes the join check: `join` directly after "why" ("Why join when there's no content?", "why join?") or directly before "us"/"our" ("Join our mailing list") does not count. "Wait for", "partial diff", a join node and "both reviews … to join" still count. By the pattern (no eval case), other membership phrasings ("join the community") still pass. Four new cases (the fixture from the item, a quoted "why join?", "Join our mailing list for updates.", and the guard "The merge step waits for both reviews to join.", which passed before the fix): 244 cases; the lab's `make test` gives 243/243 (1 skipped). |
| F13 | A bare "budget" no longer passes the budget check. It needs an amount ("budget of 30 turns", "budget: 5", "$5 budget", "5 USD budget"), a run scope ("budget per run/job/attempt/turn/task/agent") or a run noun before it (run, job, turn, cost, time, step, spend, usd, dollar, compute, attempt budget). "The user's cognitive budget is finite." and a `budget` form field no longer count. Timeout, token budget, max minutes and spend cap are unchanged. Five new cases (the two fixtures from the item, and three guards that passed before the fix: "Each run has a budget of 30 turns.", "Each run has a $5 budget." and "… its budget per run is spent."): 250 cases; the lab's `make test` gives 249/249 (1 skipped). By the pattern (no eval case), `BUDGET_USD = 5` and `max_budget` never matched `\bbudget\b` and still do not count. |
| F14 | `stuck` passes the repeated error exit check only on a line that also stops or hands off, with the same words as `twice` (stop, exit, halt, abort, end(s), escalate, give up, park or blocked), from one shared pattern: "If they're stuck, give a nudge." no longer counts. "Same error", "same failure" and the `twice` rule are unchanged. Three new cases (the fixture from the item, and two guards that passed before the fix: "When a job is stuck on the same error twice, stop and escalate." and "A job that stays stuck is parked for a human.", the second one with no other keyword): 252 cases; the lab's `make test` gives 251/251 (1 skipped). |

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
- conditional edges: "The graph has 3397 edges." and "Edge-cache is on." Done (see section 4).
- join: "`names.join(', ')`" in a code snippet in a `.md`. Done (see section 4).
- ignore outcome: "Run `git check-ignore`." and "Use `--ignore=tests/slow`." Done (see section 4).
- budget: "`setTimeout(fn, 100)`" and "Screenshots sometimes time out." Done (see section 4).
- repeated error exit: "It crashed twice last week." Done (see section 4).
- trace: "Trace the bug back to the parser." Done (see section 4).
- bounded cycle: "Cost is bounded per turn." Done (see section 4).
- attempt cap: `var attempts = 0` (no bound). Done (see section 4).
- fail closed: "Report a non-zero count." Done (see section 4).

### F4. Dutch evidence (decision 8): done (see section 4)
- human gate: "zonder akkoord", "wacht op akkoord".
- fail closed: "faalt dicht", "stop bij de eerste fout".
- The negation window also needs Dutch negators: niet, geen, nooit, zonder.

### F5. Config gate (decision 9): done (see section 4)
A review-gate config such as `hooks/review-gate.json` with `"mode": "ask"` counts as a human gate.

### F8. Speed on large repos: done (see section 4)
Measure again after F1. Target: under 10 s on 3,000 tracked files.

### F6. Secret check: Dutch key names: done (see section 4)
`wachtwoord: <literal>` in Markdown is not flagged today. Give the citation only, never the value.

### F9. "claim" as a verb about a statement: done (see section 4)
Found in the field check after F2 claim: a design doc passes "claim" with "nobody can retroactively claim they created something first". The F2 rule only excludes the noun ("a/the … claim").
- Fixture: `README.md` "Nobody can claim they created it first." Expected: claim fails.
- Guard: `README.md` "Each job is claimed by one worker." still passes.

### F10. "in progress" in plain prose: done (see section 4)
Found in the same field check: "claim" passes on a blog post's "photos of the tower build in progress", through the `in progress` pattern.
- Fixture: `README.md` "Photos of the build in progress." Expected: claim fails.
- Guard: a state file `jobs.json` with `"status": "in progress"` still passes.

### F11. "status ==" from an HTTP check counts as a conditional edge: done (see section 4)
Found in the field check after F2 conditional edges: "conditional edges" passes on `if resp.status == 200:` in a Python snippet inside a `.claude/commands/*.md`, through the `status ==` pattern in `cite_cond_edge`, which does not need the word edge.
- Fixture: `README.md` with a code block holding `if resp.status == 200:`. Expected: conditional edges fails.
- Guard: `README.md` "If status == failed, the edge goes back to fix." still passes.
- Also seen in the field check of this PR on two more repos: a count of graph edges next to a condition word still passes ("`Rebuilt: 290 nodes, 294 edges` … when the hook fired"). And `assert status == 401` inside a code block in a plan doc passes through the `status ==` pattern. Fixtures: a README line "Rebuilt: 290 nodes, 294 edges when the hook fired." and a fenced block in a `.md` with `assert status == 401`. Expected: conditional edges fails for both. A number directly before "edges" never counts.

### F12. "join" as becoming a member: done (see section 4)
Found in the field check after F2 join: two repos still pass "join" on prose like "why join when there's no content?" and "a great answer to \"why join?\"". F2 join excluded method calls (`names.join(`, `os.path.join(`), not the bare verb.
- Fixture: `README.md` "Why join when there's no content?" Expected: join fails.
- Guard: `README.md` "The merge step waits for both reviews to join." still passes.

### F13. "budget" with another meaning: done (see section 4)
Found in the field check after F2 budget: two repos still pass "budget" through bare `\bbudget\b`, on "The user's cognitive budget is finite" and on a form field list "Honeypot fields (`company_website`, `phone_number`, `budget`)". F2 budget only fixed `setTimeout`-style timeouts.
- Fixture: `README.md` "The user's cognitive budget is finite." Expected: budget fails. Also "Honeypot fields (`phone_number`, `budget`) are rejected."
- Guard: `README.md` "Each run has a budget of 30 turns." still passes.

### F14. "stuck" without a stop rule: done (see section 4)
Found in the field check after F2 repeated error exit: a coaching doc passes "repeated error exit" on "If they're stuck, give a nudge (a hint or reframe), not the answer." through bare `\bstuck\b`. F2 only tightened `twice`.
- Fixture: `README.md` "If they're stuck, give a nudge." Expected: repeated error exit fails.
- Guard: `README.md` "When a job is stuck on the same error twice, stop and escalate." still passes.

### F15. A numeric loop bound in UI code counts as an attempt cap
Found in the field check after F2 attempt cap: a site renderer passes "attempt cap" on `while (el.scrollHeight > frameH + 2 && attempts < 12) {`, a shrink-to-fit loop, through `attempt(?:s)?\s*[:=<]\s*\d`. It bounds a layout loop, not an agent's fix attempts.
- Fixture: `site/js/render.js` with `var attempts = 0;` and `while (tooTall() && attempts < 12) { attempts++; }`. Expected: attempt cap fails.
- Guard: `loop.py` with `MAX_ATTEMPTS = 3` and `if attempts >= MAX_ATTEMPTS: escalate(job)` still passes.

### F16. English parity for "stop at the first error" (decision 8)
Found in the field check after F4: a `CLAUDE.md` now passes "fail closed" on the Dutch rule "Stop bij de eerste fout — analyseer, fix, verifieer voordat je doorgaat." The English rule "Stop at the first error." does not pass, although decision 8 says Dutch counts the same as English.
- Fixture: `CLAUDE.md` "Stop at the first error." Expected: fail closed passes, like the Dutch line.
- Guard: `README.md` "The first error was a typo." still fails.

### F17. Speed target on denser filler
Found in the field check after F8: on a synthetic repo of 3,000 committed files of 200 lines of lorem ipsum, the scorer took 95.8 s before F8 and 17.7 s after it (same output) on the lab host. That is the same 5x gain F8 reports, but above the 10 s target. F8's 6 s was measured on its own fixture.
- Fixture: a timing script that builds that repo and runs the scorer once. Expected: under 10 s on the lab host, output unchanged.

### F18. A "=== Status ===" banner counts as a conditional edge
Found in the field check after F11: "conditional edges" passes on `print('=== Review Status ===\n')` in a plan doc. F11's `status ==(?!\s*\d)` matches "Status ===" because the next character is `=`, not a digit.
- Fixture: `README.md` with a code block holding `print('=== Review Status ===')`. Expected: conditional edges fails.
- Guard: `README.md` "If status == failed, the edge goes back to fix." still passes.

### F19. "join the club" as membership
Found in the field check after F12: a concept doc still passes "join" on "- Pay a membership fee to join the club". F12 caught "why join?" but not "join" with a group as its object.
- Fixture: `README.md` "Pay a membership fee to join the club." Expected: join fails. Also "Join our community."
- Guard: `README.md` "The merge step waits for both reviews to join." still passes.

### F20. An HTTP request timeout counts as a run budget
Found in the field check after F13: "budget" passes on `resp = urllib.request.urlopen(req, timeout=10)` in a code snippet inside a `.claude/commands/*.md`, through `(?<![a-z])timeout`. It limits one HTTP call, not an agent run.
- Fixture: `README.md` with a code block holding `resp = urllib.request.urlopen(req, timeout=10)`. Expected: budget fails.
- Guard: `loop.py` with `AGENT_TIMEOUT = 600` and a workflow with `timeout-minutes: 30` still pass.

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
