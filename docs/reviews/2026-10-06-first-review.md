> **Historical.** This review describes the code as it was when written. Items H1–H7 have since been fixed; current status is in `HANDOFF.md`.

# Review: agent-graph-audit v0.1

**Date:** 2026-10-06
**Scope:** `SKILL.md`, `README.md`, `references/rubric.md`, `references/failure-modes.md`, `scripts/score_setup.py`, `evals/run_evals.py`, `requirements.txt`, `LICENSE`
**Environment:** Python 3.13.16, PyYAML 6.0.3

**Legend:** ✅ reproduced by running a fixture · 📖 from reading the code only, not run

---

## Summary

- **The skill's own evals pass, 27/27.** ✅
- **The README's self-score of 69% is correct.** ✅ The raw score is **89**, not "90+" as the README says.
- **The core weakness:** most checks look for a keyword anywhere in the repo, ignore "no" and "not", and run prose keywords over code files. The 69 ceiling protects the composite score. But the layer scores and the "Next gap" recommendation are what a user acts on, and those inflate easily.
- **Highest-leverage fix:** only match the prose keyword checks in documentation files (`.md`, `.txt`), and parse config files properly. That removes most of the false passes in H6 and H7.

## What works

- Every passing check must have a file:line citation, and missing evidence scores zero.
- It fails closed when unsure.
- It labels which numbers are policy and which are measurements.
- The evals are a regression suite of known bypasses, and the human-gate set is thorough for the spellings it covers.
- The README is honest about what a score does and doesn't mean.

---

## High: wrong scores on normal repos

### H1. Installing the skill in a repo inflates that repo's score ✅

| Fixture | Score |
|---|---|
| Repo with a one-line `CLAUDE.md` | **8%** (harness/loop/graph 25 / 0 / 0) |
| Same repo with the skill copied to `.claude/skills/agent-graph-audit/` | **69%**, raw 89 (90 / 92 / 85) |

- **Cause:** the scorer reads its own docs, which name every check. The README warns about this, but `.claude/skills/` is the normal place to install a skill for a project.
- **Fix:** skip the scorer's own folder automatically. Either skip `Path(__file__).resolve().parents[1]` when it sits under the target, or skip any directory whose `SKILL.md` has `name: agent-graph-audit`.

### H2. A repo inside a folder named `build`, `dist`, `artifacts`, `venv` (or any other skip-list name) scores 0% ✅

| Fixture location | Files scanned | Score |
|---|---|---|
| `…/ok/repo` | 2 | 69% (raw 97) |
| `…/build/repo` | 0 | 0% |
| `…/dist/repo` | 0 | 0% |
| `…/artifacts/repo` | 0 | 0% |
| `…/venv/repo` | 0 | 0% |

- **Cause:** `iter_files` checks `path.parts`, which is the absolute path, so the folders above the target are tested too.
- **Fix:** test `path.relative_to(root).parts` instead.

### H3. `.env` files are never read, so "no inline secrets" passes on a committed `.env` ✅

- **Fixture:** `.env` containing `OPENAI_API_KEY=sk-proj-abc…` plus a README. Result: **no inline secrets: PASS** (`scanned:1`; only the README was read).
- **Cause 1:** `Path(".env").suffix == ""`, so the suffix filter never matches. Neither does the name allow-list (`AGENTS.md`, `CLAUDE.md`, `Makefile`, `Dockerfile`, `.gitignore`). The `.env` and `.gitignore` entries in `TEXT_SUFFIXES` only match names like `foo.env`.
- **Cause 2:** even if the file were read, `SECRET_RE` needs quotes around the value. Normal `.env` syntax (`KEY=value`) has none.
- **Fix:**
  - Include files whose name is `.env` or starts with `.env.`.
  - Add a pattern for unquoted values in those files, for example `^\s*(?:export\s+)?\w*(KEY|SECRET|TOKEN|PASSWORD)\w*\s*=\s*[^\s'"#]{12,}`.

### H4. The secret pattern misses common formats and flags good practice ✅

| Fixture | Result | Expected |
|---|---|---|
| `{"api_key": "sk-proj-abc…"}` in `config.json` | PASS (missed) | fail |
| `SECRET_KEY = "django-insecure-abc…"` | PASS (missed) | fail |
| `aws_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfi…"` | PASS (missed) | fail |
| `token = "eyJhbGci….eyJzdWIi….abc"` (JWT) | PASS (missed) | fail |
| `API_KEY="your-api-key-here"` in `.env.example` | **fail** (false positive) | pass |
| `API_KEY = "sk-proj-abc…"` in `config.py` (control) | fail (caught) | fail |

- **Causes:**
  - JSON puts a `"` between the key and the `:`.
  - The key name must end at `secret`, `token` or `password`, so `SECRET_KEY` doesn't match.
  - The value pattern `[A-Za-z0-9_\-]` excludes `/`, `+`, `.` and `=`.
  - There is no placeholder exclusion.
- **Fix:**
  - Allow extra word characters around the key name and an optional closing quote: `\w*(api[_-]?key|secret|token|password)\w*["']?\s*[:=]`.
  - Widen the value pattern to `[A-Za-z0-9_\-./+=]{12,}`.
  - Skip obvious placeholders (`your-`, `changeme`, `example`, `xxx`, `<…>`).

### H5. The human gate misses four real auto-merge spellings ✅

Each fixture also had a README containing "We have a human gate". In every case the human gate wrongly **passed**.

| Fixture | Why it slipped |
|---|---|
| `allow_auto_merge: true` (GitHub repo setting key) | `\b` before `auto` fails after `_` |
| `{"platformAutomerge": true}` (Renovate) | `\b` fails inside camelCase |
| `enablePullRequestAutoMerge(...)` (GitHub GraphQL mutation) | `\b` fails inside camelCase |
| `gh pr merge "$PR" \` then `--auto --squash` on the next line | `merge … --auto` must be on the same line |

- **Fix:**
  - Drop the leading `\b` and allow an underscore: `auto[\s_-]?merg(?:e|ed|es|ing)`. Keep the `no ` look-behind.
  - Join `\`-continued lines before running the `merge … --auto` check.
  - Add all four as fixtures.

### H6. No check understands "no" or "not" ✅

| Fixture | Checks that wrongly pass |
|---|---|
| "All agents share a single worktree and one dirty tree." | work isolation, isolated workspace |
| "We do not use a worktree." | work isolation, isolated workspace |
| "The loop has unbounded retries." | bounded cycle (`bounded` has no `\b`) |
| "There is no max attempts setting; it retries forever." | attempt cap, bounded cycle |

- The existing eval "shared dirty tree is not isolation" only passes because its sentence doesn't contain "worktree".
- The skill's own self-score cites `references/failure-modes.md:12` as isolation evidence. That is the row *describing* the shared-dirty-tree failure.
- **Fix:**
  - Use `\bbounded\b`.
  - The `max attempts` alternative must require a number.
  - Add a negation window, for example `no|not|never|without|share[sd]?|single|one` within about 4 words before the keyword. A hit there counts as no evidence, which keeps the check fail-closed.

### H7. Code files are matched with prose keywords; vendored code inflates scores ✅

| Fixture | Check that wrongly passes |
|---|---|
| `path = ", ".join(parts)` in `util.py` | join |
| `x = foo()  # type: ignore` | ignore outcome |
| "Always handle edge cases." in `CLAUDE.md` | conditional edges |
| "Fix bugs, ask for review, and respect the quality gate." | named nodes |

- **Vendored dependency:** a plain repo scored 8%. Adding one third-party file at `vendor/somelib/client.py` raised it to **27%** (harness/loop/graph 50 / 15 / 20). `vendor/` is not on the skip-list.
- **Fix:**
  - Split the corpus: prose checks run on `.md` and `.txt` only, and code or config checks use parsed structure.
  - Extend `SKIP_DIRS` with `vendor`, `target`, `.tox`, `.mypy_cache`, `.pytest_cache`, `coverage`, `.cache`, `site-packages`, `.terraform`.

---

## Medium: real setups score too low

### M1. Real state files are ignored when they're large or nested ✅

| Fixture | Counts as a runner? |
|---|---|
| `state.json`, 3,000 valid records, 324,000 bytes | **no** |
| `state.json`, one valid record (control) | yes |
| `{"jobs": [{"job_id": "j1", "status": "failed", "attempt": 1}]}` | **no** |

- **Cause:** `read_files` cuts every file at 200,000 characters before the JSON is parsed. `state_record_ok` only accepts a top-level list or a single top-level record.
- So the more history a state file has, the less it counts, which runs against the v0.2 "lived-in record" plan.
- **Fix:**
  - Parse state files from the full file, not the truncated text.
  - Also accept common wrappers (`jobs`, `records`, `items`) one level down.
  - Consider `state.jsonl` as well.

### M2. LangGraph is never recognised as a runner ✅ (GitLab and CircleCI 📖)

- **Fixture:** `langgraph.json` with a `graphs` mapping, plus `graph.py` importing `StateGraph`. Result: **running = False**.
- **Cause:** files with "langgraph" in the path are picked up, but then only pass if they contain a GitHub Actions-style top-level `jobs:` block, which they never have.
- 📖 GitLab (`.gitlab-ci.yml` has no top-level `jobs:`) and CircleCI (`.circleci/config.yml` doesn't match the path filter) are also never recognised.
- **Fix:** either remove the `langgraph` match, since it can never pass, or add a real check, for example `langgraph.json` with a `graphs` mapping. State in the README that only GitHub Actions counts for now.

### M3. Common real config fails the checks ✅

| Fixture | Check | Result |
|---|---|---|
| `MAX_RETRIES = 3` | attempt cap | fail |
| `@retry(stop=stop_after_attempt(3))` (tenacity) | attempt cap | fail |
| "Run npm run test before merging." | verify command | fail (while `npm run lint` passes) |
| `.claude/settings.json` with `{"permissions": {"allow": […], "deny": […]}}` | tool boundary | fail |
| "There is a spend cap of $5 per run." | budget | fail (see D1) |
| `pytest>=8.0` in `requirements-dev.txt` | verify command | **PASS** (false positive) |

- The settings.json case matters most, because Claude Code's own permission config doesn't count for a skill that says it scores "a Claude harness".
- **Fix:**
  - Attempt cap: add `max_retries\s*[:=]\s*\d`, `retries\s*[:=]\s*\d` and `stop_after_attempt\(\d`.
  - Verify command: add `npm run test`, `pnpm run test`, `bun test`, `vitest`, `jest` and `python -m pytest`.
  - Don't count `pytest` on a dependency line.
  - Tool boundary: parse `.claude/settings.json` `permissions.allow` / `permissions.deny`, and consider `allowed-tools` in skill or command frontmatter.
  - "Token budget of N" also counts as an attempt cap today ✅. It probably shouldn't.

---

## Docs that don't match the code

| # | What the docs say | What the code does | Basis |
|---|---|---|---|
| D1 | `rubric.md`: budget passes on "Timeout or spend cap" | No `spend cap` pattern; the fixture fails | ✅ |
| D2 | README: "scores itself 69% (raw 90+)" | raw = 89 | ✅ |
| D3 | SKILL.md: "Missing evidence is zero" | An empty, 0-byte `CLAUDE.md` passes the instruction-file check, citing a line 1 that doesn't exist | ✅ |
| D4 | External state: "job id, status, and attempt stored outside the chat" | Status is never checked; only the `job_id` line is cited, and `attempt` is required but not cited | 📖 |
| D5 | With PyYAML missing: "Do not read this as a missing runner" | The same report's cap line says "no real runner or state file caps the composite at 69" | 📖 |
| D6 | SKILL.md frontmatter `type: workflow`, `lifecycle: active` | The skill-creator validator (`quick_validate.py`) rejects both keys. Not verified whether Claude Code itself ignores or rejects them. | ✅ (validator only) |

## Low

- **L1. Crash on a nested state file.** ✅ A `state.json` with 100,000 levels of nested arrays exits 1 with an uncaught `RecursionError`. Catch `RecursionError` and `ValueError` next to `JSONDecodeError`.
- **L2. The evals hide packages installed with `pip install --user`.** ✅ / 📖 `run_evals.py` runs the scorer with `python -I`, which turns user site-packages off (confirmed: `site.ENABLE_USER_SITE` is False). If PyYAML was installed with `pip install --user`, the "real workflow" eval should fail. That knock-on failure was not reproduced. Either document "install PyYAML in a venv or system-wide", or use `-s -E` without `-I`.
- **L3. Dead code.** ✅ `file_text()` is never called. `names = names_blob(files)` in `harness_checks` is never used.
- **L4. One crash stops the whole eval run.** 📖 `run_evals.score()` uses `check=True`, so a scorer crash aborts every remaining case instead of reporting that case as FAIL.
- **L5. Redundant scanning.** 📖 Each check runs `cite_any` twice, once for the result and once for the citation. This is fine for small repos and slow on large ones. Compute each citation once.
- **L6. `.gitignore` check matches too loosely.** 📖 It matches any `\.env`, including `.envrc` and the un-ignore line `!.env.example`. A `.gitignore` containing only `!.env.example` would pass.

---

## Eval coverage gaps 📖

No fixture currently covers:

- the secret check (no positive or negative case)
- the attempt-cap pattern
- `SKIP_DIRS`, including the H2 bug
- a case where the graph cap `min(graph, loop + 20)` actually lowers the score
- a case where the "harness under 40 → 49" cap actually lowers the score (the "one-line readme" case has raw 3, so the cap never binds)
- the PyYAML-missing path
- any H5 auto-merge spelling, any H6 negation, any H7 code-token case
- any M1, M2 or M3 case

**Suggestion:** add every ✅ fixture in this review to `CASES`, since each one is a bypass or a false negative found in review, which matches how the suite is meant to grow.

---

## Suggested fix order

1. **H2** (absolute-path skip). A one-line fix that turns some repos from 0% into a correct score.
2. **H1** (skip the scorer's own folder). This is the default install location, so it affects most users.
3. **H3 + H4** (secret scanning). This check currently gives false assurance.
4. **H5** (auto-merge spellings). This check is the safety-relevant one.
5. **H7 + H6** (prose checks on docs only, plus a negation window). The biggest accuracy gain.
6. **M1–M3**, then the D items, then the L items.
7. Add every fixture above to `run_evals.py` and update the README case count.
