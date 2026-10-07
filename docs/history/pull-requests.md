# Pull requests before the repository was recreated

The repository was recreated on 2026-10-07 to make it public with a clean history. These are the descriptions of the five pull requests merged before that. The commits themselves are all in `main`.

## #1 Finish v0.2: HANDOFF open work (D6, M1+L1, M3, M2, D3-D5, L2, L4-L6, eval gaps)

Merged 2026-10-06.

Evals went from 105 to 154 and all pass (`python evals/run_evals.py` gives 154/154). `python scripts/score_setup.py --target .` still reports "Skipped: the target is this skill itself". Each item has its own commit, with the failing eval output quoted in the commit message. No existing eval case was changed or removed. The only edits to existing lines in `evals/run_evals.py` are runner code: the `SCORER` definition, the `score()` call, the per-case crash handling and the expectation-keys comment.

## Items
- **D6**: done. SKILL.md frontmatter is now `name` and `description` only. The `harness-creator` pointer is removed.
- **M1+L1**: done. State files are parsed in full. `jobs`, `records` and `items` wrappers count. `state.jsonl` and `jobs.jsonl` are read. Bad or deeply nested JSON no longer crashes the scorer.
- **M3**: done. All five false negatives now pass and both false positives now fail. Two guard cases cover empty permission lists and an `allow` list outside `.claude`.
- **M2**: done, smaller option (see below).
- **D3**: done. An empty `CLAUDE.md` or `AGENTS.md` no longer passes.
- **D4**: done. External state requires `job_id`, `status` and `attempt`, and cites all three.
- **D5**: done. The PyYAML-missing note now says the runner is "unconfirmed". New evals cover the PyYAML-missing path.
- **L2**: done. The evals use `-E -P` instead of `-I`, so a user-site PyYAML is visible.
- **L4**: done. A scorer crash now fails the cases that hit it, not the whole run.
- **L5**: done. The three citations are computed once.
- **L6**: done. Secret ignore needs a `.gitignore` line that ignores `.env` itself.
- **Eval gaps**: done. Cases pin the graph cap and the harness-under-40 cap.
- Parked: none.

## Choices I made
- **M2**: I removed the dead `langgraph` path match and documented "GitHub Actions only" in the README, `references/rubric.md` and `HANDOFF.md`. GitLab, CircleCI and LangGraph projects are not recognised as runners. A `state.json` shows a runner for them.
- **M1**: `jobs`, `records` and `items` wrappers count one level down. Only `state.jsonl` and `jobs.jsonl` are added as new file names. State files are read up to 50M characters.
- **M3**: `requirements*.txt` files are not searched for verify commands. A `pytest` followed by a version specifier or extras is treated as a dependency. The `.claude/settings*.json` tool boundary needs a non-empty `allow` or `deny` list.
- **L2**: `HANDOFF.md` suggested `-s -E`, but `-s` is the flag that hides the user site. I used `-E -P`, and the new eval fails with `-I` and passes with `-E -P`.
- **L6**: `cite_named` became unused, so I removed it.
- **Eval-runner additions**: `EVAL_SCORER` swaps in another scorer, and only the crash check uses it. `raw` and `graph_effective` can now be asserted.

## Decisions for Micha
- **Cap evals**: the three cap cases, and the PyYAML-missing "score and note" case, pass on the code before and after. They pin existing behaviour, so they could not be shown failing first. I checked the cap cases by mutation: with the graph slack and the 49 cap loosened, two of them fail.
- **L5 probe eval**: it is mine, added on this branch. I changed it once in the L6 commit, to count `gitignore_env_cite` instead of `cite_named`. The assertion is the same.
- **GitLab/CircleCI**: do you want real checks for them in a later version, or is "GitHub Actions only" enough?
- **Merge**: I did not merge or enable auto-merge. Merging is yours.



---

## #2 L2 eval: never write the stub yaml outside its temp folder

Merged 2026-10-06.

On Windows the L2 eval wrote a stub `yaml.py` into the real user site (`%APPDATA%\Python\...\site-packages`), shadowing PyYAML machine-wide. Found while installing locally after merging #1. Fix: redirect APPDATA too, query the site with the scorer's flags, refuse to write outside the temp folder. 154/154 on Windows; the real user site stays clean. Merge is manual (human gate).

## #3 HANDOFF: field-test round 1 (F1-F8) and decisions 8-9

Merged 2026-10-06.

Docs only. Records the first field-test round (6 real repos, citations checked by hand: 54 false passes vs 35 true passes, 7 false fails) as open items F1-F8 with synthetic reproduction cases, and Micha's decisions 8 (Dutch evidence counts) and 9 (a review-gate config with ask mode counts as human gate). No code or eval changes; 154/154. Merge is manual (human gate).

## #4 L2 eval: skip in a plain venv; lab findings added to F3

Merged 2026-10-06.

Two findings from the lab setup on a home server.

1. **L2 eval in a plain venv.** `python3 -m venv` turns the user site off, so the L2 eval could never load its stub and failed (153/154). It now raises `Skip` when `site.ENABLE_USER_SITE` is not True. Verified on Windows: system Python 154/154, plain venv 153/153 (1 skipped). This changes an existing eval case (the L2 one): it skips instead of failing in that environment; the assertion itself is unchanged.
2. **Weakest-hit citations (F3).** Two more cases added to HANDOFF F3: external state cites a Makefile `.PHONY ... status` line, and work isolation cites a Makefile comment, while stronger evidence exists. Plus a general preference order.

Merge is manual (human gate).

## #5 F1: skip ignored paths and .claude/worktrees (from the lab), plus F1b

Merged 2026-10-07.

**First job delivered by the lab on a home server** (job `f1`, attempt 1: verify green, review pass). Imported here as a patch, since the skill repo is the source of truth; the lab will re-import from main and does not merge its job branches itself.

- The scorer no longer walks `.claude/worktrees/` and skips paths an in-tree `.gitignore` ignores (simple matcher). Exceptions per Micha: state files are still read; an ignored `.env` no longer fails inline secrets.
- 6 cases added, 0 existing lines changed in `run_evals.py`. 160/160 on Windows (Python 3.12) and in the lab.
- Field check on 6 real repos: files scanned down 3-6x (e.g. 1915 → 319), runs from 12-48 s to ≤3 s. Two false passes gone (graph cache, browser snapshot). One new false fail: a repo that ignores all of `.claude/` lost its `settings.json` allow list. That is recorded as **F1b** in HANDOFF (decision: `.claude/settings*.json` still count) and becomes the next job.

Merge is manual (human gate).
