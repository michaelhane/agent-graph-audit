---
name: agent-graph-audit
description: "Score an agent setup as a percentage on harness, loop, and graph readiness. Use when the user asks to audit a repo, check if a workflow is a real graph, check looping, or score a Claude or agent harness."
---

# Agent Graph Audit — Score the setup

Score a folder or repo on three layers. Report percentages. Do not invent a passing grade from a chat description if the files are available.

Not for writing a new harness from scratch. Not for prompt tuning.

This version is a claim-tier scorer. It matches text and parsed files. It does not execute the loop.

## Run

Requires PyYAML to judge workflow files. State files do not need it.

```bash
python3 scripts/score_setup.py --target /path/to/setup
python3 scripts/score_setup.py --target /path/to/setup --json
```

If PyYAML is missing and a workflow file is present, the score stays fail-closed and the report says `runner check skipped: pyyaml not installed`. That is not a missing runner. If no workflow file is present, no note appears.

If the user only pasted a design, write it to a temp folder first and score that folder. Say the score is of the paste, not of a running system.

## Report

1. Composite percentage.
2. Harness, loop, and graph percentages.
3. The first missing check in list order on the lowest layer. Ties between layers go to harness, then loop, then graph. Not the highest-weight missing check.
4. One sentence if a cap fired. Caps are policy, not measurements.
5. Whether a runner or state file exists. If not, call the graph a claim. If the runner check was skipped, say that and do not call the runner missing.

Read `references/rubric.md` before explaining weights. Read `references/failure-modes.md` if the score is high and the user is about to let the agent merge.

## Rules

- Missing evidence is zero. Do not award points for intent.
- A pass with no file:line citation is a fail. The absence check cites `scanned:N` and needs a scan of at least one file. An empty corpus scores 0.
- Graph credit is min(graph, loop + 20). That slack is policy, not a measurement.
- Harness under 40 caps the composite at 49. No real runner or state file caps it at 69. Both are policy.
- A state file counts only if it parses and has a record with a non-empty `job_id`, `status` in the known set (`open`, `claimed`, `in_progress`, `running`, `passed`, `failed`, `ignored`, `escalated`, `done`), and `attempt` as an int ≥ 0. Nulls and keys-as-text do not count.
- A workflow counts only if YAML parses and top-level `jobs` is a mapping with at least one job that has `runs-on` or `steps`. A comment that mentions steps does not count.
- Any such CI job counts until evidence tiers. A plain lint workflow lifts the ceiling. Tiers will require the workflow to reference the loop.
- Repeated-error pays 7 of 15, denominator stays 100, until a fingerprint exists (normalized message plus the failing command). A full pass can still show loop 92.
- Call a README-only graph a claim.
- A negated mention is not evidence: "we do not use a worktree", "no allowlist", "unbounded retries". See `references/rubric.md` for the window rule.
- Graph checks and the loop's claim, fail-closed and repeated-error checks match words in docs and config, not code comments. Code counts for the graph only through graph-builder calls (`add_node`, `add_conditional_edges`, `add_edge([a, b], c)`) and numeric bounds.
- Human gate needs a gate phrase, and fails on unnegated auto-merge in any spelling or word form (`auto-merge`, `automerge`, `auto merge`, `auto-merged`, `auto-merges`, `auto-merging`), including inside identifiers (`allow_auto_merge`, `platformAutomerge`, `enablePullRequestAutoMerge`), or `merge` followed by `--auto` on the same line (`gh pr merge 42 --auto --squash`). Lines ending in a backslash count as one line with the next. `no auto-merge` still passes. `never auto-merge` fails closed. This is a phrase check, not a permission check. Do not raise autonomy recommendations when it failed, and do not treat a pass as proof the agent cannot merge.
- After scoring, name the single next artifact to add. Do not list a redesign.

## Known limits

- The scorer matches text and parsed files. It does not execute the loop.
- Any CI job counts as a runner until evidence tiers ship.
- Human gate fails on unnegated auto-merge phrasings and `merge ... --auto`. Negations other than `no` (`never`, `disabled`) also fail, and so does a setting turned off (`allow_auto_merge: false`); that is deliberate, fail closed. If the gate failed, the check's `why` names the file and line where auto-merge was found. A pass is still not proof of who can merge.
- Folders that are this skill (frontmatter `name: agent-graph-audit`, or the `scripts/score_setup.py` + `references/rubric.md` layout) are skipped and listed in the report. If the report says the target itself was skipped, tell the user they pointed it at the skill, not at their setup.
- The secret check flags a key name assigned a quoted literal, or an unquoted value in a `.env`-style file. It is not a secret scanner.
- Run `python3 evals/run_evals.py` after any change to a pattern. Every fixture in it is a bypass or regression found in review.

## Knowledge graph

Start at `references/rubric.md`.
