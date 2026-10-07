#!/usr/bin/env python3
"""Regression evals for score_setup.py.

Every case below is a bypass or bug found during review. Each builds a tiny
fixture folder, scores it, and checks the result. Exit code 0 means all pass.

    python3 evals/run_evals.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# EVAL_SCORER swaps in another scorer. Only the crash check below uses it.
SCORER = Path(os.environ.get("EVAL_SCORER") or Path(__file__).resolve().parent.parent / "scripts" / "score_setup.py")

# A README that names every keyword. Scores high on text, has no runner.
STUFFED = (
    "CLAUDE.md definition of done. npm test. worktree. allowlist. trace. timeout.\n"
    "claim. max_attempts 3. fail closed. same error twice. per job.\n"
    "nodes: intake -> triage -> fix -> review -> gate -> planner. tests passed. job_id status attempt.\n"
    "human gate. ignore. bounded. join.\n"
)
STUFFED_FILES = {"README.md": STUFFED, ".gitignore": ".env\n"}

REAL_WF = (
    "on: push\njobs:\n  fix:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: npm test\n"
)


def with_stuffed(extra: dict[str, str]) -> dict[str, str]:
    return {**STUFFED_FILES, **extra}


def gate_case(line: str) -> dict[str, str]:
    return {"README.md": f"{line}\nWe have a human gate.\n"}


# (name, files, expectations)
# Expectation keys: final, running, harness, loop, graph, raw, graph_effective, and pass:<check>/fail:<check>.
CASES = [
    # Baselines
    ("empty", {}, {"final": 0}),
    ("one-line readme", {"README.md": "agents are cool\n"},
     {"final": 3, "harness": 10, "loop": 0, "graph": 0}),
    ("stuffed readme hits claim ceiling", STUFFED_FILES,
     {"final": 69, "running": False, "loop": 92}),

    # Runner detection bypasses
    ("empty state.json", with_stuffed({"state.json": "{}"}), {"final": 69, "running": False}),
    ("keys as text", with_stuffed({"state.json": '{"note": "job_id status attempt"}'}),
     {"final": 69, "running": False}),
    ("null record", with_stuffed({"state.json": '{"job_id": null, "status": null, "attempt": null}'}),
     {"final": 69, "running": False}),
    ("workflow without jobs", with_stuffed({"workflow.yml": "name: x\non: push\n"}),
     {"final": 69, "running": False}),
    ("comment mentions steps", with_stuffed({"workflow.yml": "name: x\n# TODO add steps: later\n"}),
     {"final": 69, "running": False}),

    # True positives
    ("real state record",
     with_stuffed({"state.json": '[{"job_id":"j1","status":"failed","attempt":1}]'}),
     {"final": 97, "running": True}),
    ("real workflow", with_stuffed({".github/workflows/agent.yml": REAL_WF}),
     {"final": 97, "running": True}),

    # Real state files (review item M1, with L1).
    ("state: 324 KB file is parsed in full", with_stuffed({"state.json": json.dumps(
        [{"job_id": f"job-{n:05d}", "status": "passed", "attempt": 1, "note": "x" * 40} for n in range(3000)])}),
     {"final": 97, "running": True}),
    ("state: jobs wrapper", with_stuffed({"state.json": json.dumps(
        {"jobs": [{"job_id": "j1", "status": "failed", "attempt": 1}]})}),
     {"final": 97, "running": True}),
    ("state: records wrapper", with_stuffed({"jobs.json": json.dumps(
        {"records": [{"job_id": "j1", "status": "failed", "attempt": 1}]})}),
     {"final": 97, "running": True}),
    ("state: items wrapper", with_stuffed({"state.json": json.dumps(
        {"items": [{"job_id": "j1", "status": "failed", "attempt": 1}]})}),
     {"final": 97, "running": True}),
    ("state: jsonl", with_stuffed({"state.jsonl": (
        '{"job_id": "j1", "status": "failed", "attempt": 1}\n{"job_id": "j2", "status": "open", "attempt": 0}\n')}),
     {"final": 97, "running": True}),
    ("state: wrapper with empty records is not a runner", with_stuffed({"state.json": json.dumps(
        {"jobs": [{"job_id": None, "status": "failed", "attempt": 1}]})}),
     {"final": 69, "running": False}),
    ("state: 100k nested brackets does not crash", with_stuffed({"state.json": "[" * 100_000}),
     {"final": 69, "running": False}),

    # Single-check bugs
    ("verifier word alone", {"README.md": "The verifier is a single word here.\n"},
     {"fail:verify command": True, "fail:evidence verify": True}),
    ("readme mentions .env, gitignore does not",
     {"README.md": "Copy .env.example to .env\n", ".gitignore": "node_modules\n"},
     {"fail:secret ignore": True}),
    ("shared dirty tree is not isolation",
     {"README.md": "Two jobs share one branch, so we get a shared dirty tree.\n"},
     {"fail:work isolation": True, "fail:isolated workspace": True}),

    # Human gate: must fail
    ("gate: auto-merge", gate_case("The merge node uses auto-merge when tests pass."), {"fail:human gate": True}),
    ("gate: automerge", gate_case("Uses automerge."), {"fail:human gate": True}),
    ("gate: auto merge", gate_case("Uses auto merge."), {"fail:human gate": True}),
    ("gate: auto-merged", gate_case("PRs are auto-merged on green."), {"fail:human gate": True}),
    ("gate: auto-merges", gate_case("The bot auto-merges PRs."), {"fail:human gate": True}),
    ("gate: auto-merging", gate_case("Auto-merging is enabled."), {"fail:human gate": True}),
    ("gate: merge --auto", gate_case("Run gh pr merge --auto."), {"fail:human gate": True}),
    ("gate: merge <n> --auto --squash", gate_case("Run gh pr merge 42 --auto --squash."), {"fail:human gate": True}),
    ("gate: merge --squash --auto", gate_case("Run gh pr merge --squash --auto."), {"fail:human gate": True}),
    ("gate: enable-auto-merge", gate_case("enable-auto-merge on green."), {"fail:human gate": True}),
    ("gate: never auto-merge (fail closed)", gate_case("We never auto-merge."), {"fail:human gate": True}),
    # Spellings that slipped past the word-boundary pattern (review item H5).
    ("gate: allow_auto_merge key", gate_case("allow_auto_merge: true"), {"fail:human gate": True}),
    ("gate: renovate platformAutomerge", gate_case('{"platformAutomerge": true}'), {"fail:human gate": True}),
    ("gate: graphql enablePullRequestAutoMerge",
     gate_case("mutation { enablePullRequestAutoMerge(input: $i) { clientMutationId } }"),
     {"fail:human gate": True}),
    ("gate: --auto on a continuation line", gate_case('gh pr merge "$PR" \\\n  --auto --squash'),
     {"fail:human gate": True}),
    ("gate: --auto two continuations down", gate_case('gh pr merge \\\n  "$PR" \\\n  --squash --auto'),
     {"fail:human gate": True}),
    ("gate: allow_auto_merge false (fail closed)", gate_case("allow_auto_merge: false"),
     {"fail:human gate": True}),

    # Human gate: must pass
    ("gate: no auto-merge", gate_case("No auto-merge."), {"pass:human gate": True}),
    ("gate: plain human gate", {"README.md": "We have a human gate.\n"}, {"pass:human gate": True}),
    ("gate: mergeable is not merge --auto", gate_case("Check that the PR is mergeable automatically."),
     {"pass:human gate": True}),
    ("gate: continued merge without --auto", gate_case('gh pr merge "$PR" \\\n  --squash'),
     {"pass:human gate": True}),
    ("gate: --auto on a separate command", gate_case("gh pr merge 42 --squash\nnpm run release -- --auto"),
     {"pass:human gate": True}),
    ("gate: no-auto-merge label", gate_case("Label PRs no-auto-merge."), {"pass:human gate": True}),

    # Secrets: must fail
    ("secret: unquoted .env", {"README.md": "readme\n", ".env": "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz\n"},
     {"fail:no inline secrets": True}),
    ("secret: json api_key", {"config.json": '{"api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz"}\n'},
     {"fail:no inline secrets": True}),
    ("secret: SECRET_KEY", {"config.py": 'SECRET_KEY = "django-insecure-abcdefghijklmnopqrstuvwxyz"\n'},
     {"fail:no inline secrets": True}),
    ("secret: aws slash", {"config.py": 'aws_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n'},
     {"fail:no inline secrets": True}),
    ("secret: jwt dots", {"config.py": 'token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"\n'},
     {"fail:no inline secrets": True}),

    ("secret: .envrc export",
     {"README.md": "readme\n", ".envrc": "export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz\n"},
     {"fail:no inline secrets": True}),
    ("secret: kwarg literal", {"client.py": 'client = OpenAI(api_key="sk-proj-abcdefghijklmnopqrstuvwxyz")\n'},
     {"fail:no inline secrets": True}),

    # Secrets: must pass
    ("secret: placeholder", {".env.example": 'API_KEY="your-api-key-here"\n'},
     {"pass:no inline secrets": True}),
    # Safe patterns the first h1-h4 patch flagged. Each one must pass.
    ("secret: js process.env", {"client.js": "const apiKey = process.env.OPENAI_API_KEY;\n"},
     {"pass:no inline secrets": True}),
    ("secret: py os.environ.get", {"client.py": 'api_key = os.environ.get("OPENAI_API_KEY")\n'},
     {"pass:no inline secrets": True}),
    ("secret: settings lookup", {"views.py": "secret_key = settings.SECRET_KEY\n"},
     {"pass:no inline secrets": True}),
    ("secret: tokenizer", {"model.py": 'tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")\n'},
     {"pass:no inline secrets": True}),
    ("secret: file path", {"auth.py": 'token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"\n'},
     {"pass:no inline secrets": True}),
    ("secret: type annotation", {"models.py": "    access_token: AccessTokenResponse\n"},
     {"pass:no inline secrets": True}),
    ("secret: placeholder underscores", {".env.example": "API_KEY=your_api_key_here\n"},
     {"pass:no inline secrets": True}),
    ("secret: placeholder caps", {".env.example": 'API_KEY="YOUR_API_KEY_HERE"\n'},
     {"pass:no inline secrets": True}),
    ("secret: placeholder sk-xxxx", {".env.example": "OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx\n"},
     {"pass:no inline secrets": True}),
    ("secret: env var name as value", {"config.json": '{"api_key_env": "ANTHROPIC_API_KEY"}\n'},
     {"pass:no inline secrets": True}),
    ("secret: url is not a value", {"auth.py": 'token_url = "https://oauth2.googleapis.com/token"\n'},
     {"pass:no inline secrets": True}),
    ("secret: actions secret ref", {"ci.yml": "token: ${{ secrets.GITHUB_TOKEN }}\n"},
     {"pass:no inline secrets": True}),
    # Negation (review item H6): a negated or shared mention is not evidence.
    ("neg: share a single worktree", {"README.md": "All agents share a single worktree and one dirty tree.\n"},
     {"fail:work isolation": True, "fail:isolated workspace": True}),
    ("neg: do not use a worktree", {"README.md": "We do not use a worktree.\n"},
     {"fail:work isolation": True, "fail:isolated workspace": True}),
    ("neg: worktrees are not used", {"README.md": "Worktrees are not used.\n"},
     {"fail:work isolation": True, "fail:isolated workspace": True}),
    ("neg: unbounded retries", {"README.md": "The loop has unbounded retries.\n"},
     {"fail:bounded cycle": True}),
    ("neg: no max attempts", {"README.md": "There is no max attempts setting; it retries forever.\n"},
     {"fail:attempt cap": True, "fail:bounded cycle": True}),
    ("neg: no allowlist, no timeout", {"README.md": "There is no allowlist and we run without a timeout.\n"},
     {"fail:tool boundary": True, "fail:budget": True}),
    ("neg: never claim", {"README.md": "Workers never claim a job.\n"}, {"fail:claim": True}),
    ("neg: don't wait for", {"README.md": "Nodes don't wait for siblings.\n"}, {"fail:join": True}),
    # Negation must not swallow correct sentences.
    ("neg ok: its own worktree", {"README.md": "Each job gets its own worktree.\n"},
     {"pass:work isolation": True, "pass:isolated workspace": True}),
    ("neg ok: one worktree per job", {"README.md": "One worktree per job.\n"},
     {"pass:work isolation": True, "pass:isolated workspace": True}),
    ("neg ok: single worktree per job", {"README.md": "A single worktree per job; jobs never share one.\n"},
     {"pass:work isolation": True, "pass:isolated workspace": True}),
    ("neg ok: negation in another clause", {"README.md": "Never share state, use a worktree per job.\n"},
     {"pass:work isolation": True, "pass:isolated workspace": True}),
    ("neg ok: max 3 attempts", {"README.md": "Max 3 attempts per job.\n"}, {"pass:attempt cap": True}),
    ("neg ok: typed max_attempts", {"loop.py": "    max_attempts: int = 3\n"}, {"pass:attempt cap": True}),
    ("neg ok: edge back after not", {"README.md": "If tests do not pass, edge back to fix.\n"},
     {"pass:conditional edges": True}),
    ("neg ok: bounded by max_attempts", {"README.md": "Retries are bounded by max_attempts: 3.\n"},
     {"pass:bounded cycle": True, "pass:attempt cap": True}),

    # Prose words in code, and common words in docs (review item H7).
    ("code: str.join is not a join", {"util.py": 'path = ", ".join(parts)\n'}, {"fail:join": True}),
    ("code: type ignore is not an outcome", {"util.py": "x = foo()  # type: ignore\n"},
     {"fail:ignore outcome": True}),
    ("config: dependabot ignore key", {"dependabot.yml": "ignore:\n  - dependency-name: lodash\n"},
     {"fail:ignore outcome": True}),
    ("docs: edge cases are not edges", {"CLAUDE.md": "Always handle edge cases.\n"},
     {"fail:conditional edges": True}),
    ("docs: common words are not nodes",
     {"CLAUDE.md": "Fix bugs, ask for review, and respect the quality gate.\n"},
     {"fail:named nodes": True}),
    ("docs: Node.js is not graph context",
     {"CLAUDE.md": "Use Node 20. Fix lint, request review, pass the gate.\n"},
     {"fail:named nodes": True}),
    ("skip: vendor folder", {"CLAUDE.md": "Be helpful.\n", "vendor/somelib/client.py": (
        '"/".join(parts)  # type: ignore\ndef call(retry=3, timeout=30):\n'
        "    # raise on non-zero exit code; trace each tool call\n")},
     {"final": 8, "loop": 0, "graph": 0}),
    ("skip: venv by pyvenv.cfg", {"CLAUDE.md": "Be helpful.\n", "py312/pyvenv.cfg": "home = /usr/bin\n",
                                  "py312/lib/x.py": "trace timeout join retry 3 non-zero worktree\n"},
     {"final": 8, "loop": 0, "graph": 0}),
    ("skip: license text says ANY CLAIM", {"LICENSE.md": (
        "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES\n")},
     {"fail:claim": True}),
    ("code: comments are not loop evidence", {"util.py": (
        "# non-zero in the result\n# Same error message as for issubclass(1, int).\n"
        "# Year is bounded this way\n")},
     {"fail:fail closed": True, "fail:repeated error exit": True, "fail:bounded cycle": True}),
    ("code: Makefile join.h is not a join", {"Makefile": "SRC = Objects/stringlib/join.h\n"},
     {"fail:join": True}),
    # Real graph evidence must still count.
    ("graph: recursion_limit in code", {"run.py": 'graph.invoke(state, {"recursion_limit": 25})\n'},
     {"pass:bounded cycle": True}),
    ("graph: join at end of sentence", {"README.md": "Both branches meet at a join.\n"}, {"pass:join": True}),
    ("graph: arrows name nodes", {"README.md": "intake --> triage --> fix\n"}, {"pass:named nodes": True}),
    ("graph: backticked nodes", {"README.md": "The `planner`, `executor` and `verifier` run in order.\n"},
     {"pass:named nodes": True}),
    ("graph: langgraph code", {"graph.py": (
        'g.add_node("plan", plan)\ng.add_node("act", act)\ng.add_node("check", check)\n'
        'g.add_conditional_edges("check", route)\ng.add_edge(["plan", "act"], "check")\n')},
     {"pass:named nodes": True, "pass:conditional edges": True, "pass:join": True}),
    ("graph: ignored status value", {"state.json": '[{"job_id": "j1", "status": "ignored", "attempt": 0}]\n'},
     {"pass:ignore outcome": True}),
    ("graph: workflow needs two jobs", {".github/workflows/ci.yml": (
        "on: push\njobs:\n  merge:\n    needs: [build, test]\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo ok\n")},
     {"pass:join": True}),
    ("graph: conditional edge in docs", {"README.md": "Conditional edge: review -> gate when tests pass.\n"},
     {"pass:conditional edges": True}),

    # .gitignore must ignore .env itself (review item L6).
    ("gitignore: .envrc is not .env", {".gitignore": ".envrc\n"}, {"fail:secret ignore": True}),
    ("gitignore: un-ignore line is not an ignore", {".gitignore": "!.env.example\n"}, {"fail:secret ignore": True}),
    ("gitignore: comment is not an ignore", {".gitignore": "# keep .env out\n"}, {"fail:secret ignore": True}),
    ("gitignore: .env.example alone", {".gitignore": ".env.example\n"}, {"fail:secret ignore": True}),
    ("gitignore: .env", {".gitignore": "node_modules\n.env\n"}, {"pass:secret ignore": True}),
    ("gitignore: /.env", {".gitignore": "/.env\n"}, {"pass:secret ignore": True}),
    ("gitignore: .env*", {".gitignore": ".env*\n!.env.example\n"}, {"pass:secret ignore": True}),
    ("gitignore: *.env", {".gitignore": "*.env\n"}, {"pass:secret ignore": True}),
    ("gitignore: **/.env", {".gitignore": "**/.env\n"}, {"pass:secret ignore": True}),
    ("gitignore: .env with trailing space", {".gitignore": ".env  \n"}, {"pass:secret ignore": True}),

    # Instruction file and external state (review items D3, D4).
    ("instruction: empty CLAUDE.md", {"CLAUDE.md": ""}, {"fail:instruction file": True}),
    ("instruction: whitespace-only AGENTS.md", {"AGENTS.md": "\n  \n"}, {"fail:instruction file": True}),
    ("instruction: CLAUDE.md with text", {"CLAUDE.md": "\nBe careful.\n"}, {"pass:instruction file": True}),
    ("state: job_id and attempt without status", {"README.md": "Each record has a job_id and an attempt.\n"},
     {"fail:external state": True}),
    ("state: status alone", {"README.md": "Each record has a status.\n"}, {"fail:external state": True}),
    ("state: all three words", {"README.md": "Each record has a job_id, a status and an attempt.\n"},
     {"pass:external state": True}),

    # Caps that change the result (review eval gaps). A real state file lifts the 69 ceiling,
    # so only the cap under test can move the score.
    ("cap: graph credit is limited to loop + 20", {
        "state.json": '[{"job_id":"j1","status":"failed","attempt":1}]',
        "README.md": "nodes: intake -> triage -> fix.\nIf tests passed, go on. human gate. ignore. bounded. join.\n"},
     {"running": True, "harness": 10, "loop": 0, "graph": 100, "graph_effective": 20, "raw": 9, "final": 9}),
    ("cap: graph credit within loop + 20 is not reduced", {
        "state.json": '[{"job_id":"j1","status":"failed","attempt":1}]',
        "README.md": STUFFED},
     {"running": True, "graph_effective": 100}),
    ("cap: harness under 40 caps the composite at 49", {
        "state.json": '[{"job_id":"j1","status":"failed","attempt":1}]',
        "README.md": (
            "npm test. worktree per job. claim. max_attempts 3. fail closed. same error twice.\n"
            "nodes: intake -> triage -> fix.\nIf tests passed, go on. human gate. ignore. bounded. join.\n"
            "job_id status attempt.\n")},
     {"running": True, "harness": 35, "raw": 77, "final": 49}),

    # Runner detection is GitHub Actions only (review item M2, smaller option).
    ("runner: langgraph path is not a workflow", with_stuffed({"langgraph/pipeline.yml": REAL_WF}),
     {"final": 69, "running": False}),
    ("runner: langgraph project is not a runner", with_stuffed({
        "langgraph.json": '{"graphs": {"agent": "./agent.py:graph"}}',
        "agent.py": "g = StateGraph(State)\n"}),
     {"final": 69, "running": False}),
    ("runner: gitlab ci is not recognised", with_stuffed({".gitlab-ci.yml": REAL_WF}),
     {"final": 69, "running": False}),
    ("runner: circleci is not recognised", with_stuffed({".circleci/config.yml": REAL_WF}),
     {"final": 69, "running": False}),
    ("runner: workflow.yml still counts", with_stuffed({"workflow.yml": REAL_WF}),
     {"final": 97, "running": True}),

    # Common real config (review item M3). False negatives: these must pass.
    ("config: MAX_RETRIES constant", {"loop.py": "MAX_RETRIES = 3\n"}, {"pass:attempt cap": True}),
    ("config: tenacity stop_after_attempt", {"loop.py": "@retry(stop=stop_after_attempt(3))\ndef call(): ...\n"},
     {"pass:attempt cap": True}),
    ("config: npm run test", {"README.md": "Run npm run test before merging.\n"}, {"pass:verify command": True}),
    ("config: claude settings permissions", {".claude/settings.json": json.dumps(
        {"permissions": {"allow": ["Bash(npm test)"], "deny": ["Read(./.env)"]}})},
     {"pass:tool boundary": True}),
    ("config: spend cap", {"README.md": "There is a spend cap of $5 per run.\n"}, {"pass:budget": True}),
    # False positives: these must fail.
    ("config: pytest dependency line", {"requirements-dev.txt": "pytest>=8.0\n"}, {"fail:verify command": True}),
    ("config: pytest in pyproject dependencies", {"pyproject.toml": 'dependencies = ["pytest>=8.0"]\n'},
     {"fail:verify command": True}),
    ("config: token budget is not an attempt cap", {"README.md": "We have a token budget of 50000.\n"},
     {"fail:attempt cap": True}),
    ("config: empty claude permissions", {".claude/settings.json": '{"permissions": {"allow": [], "deny": []}}'},
     {"fail:tool boundary": True}),
    ("config: allow list outside .claude", {"cors.json": '{"allow": ["https://example.com"]}'},
     {"fail:tool boundary": True}),

    # Found in Python's own stdlib (email/_header_value_parser.py) during review.
    ("secret: descriptor key token_type", {"parser.py": "    token_type = 'unstructured'\n"},
     {"pass:no inline secrets": True}),
    ("secret: descriptor key camelCase", {"config.json": '{"tokenType": "bearer-access-token"}\n'},
     {"pass:no inline secrets": True}),

    # Scan scope (field-test item F1): .claude/worktrees/ copies and .gitignore'd paths are not read.
    ("scope: gitignored folder is not evidence", {".gitignore": "cache/\n",
                                                  "cache/notes.md": "human gate. a join node.\n"},
     {"fail:human gate": True, "fail:join": True}),
    ("scope: .claude/worktrees copy is not evidence", {".claude/worktrees/w1/CLAUDE.md": "Be careful.\n"},
     {"fail:instruction file": True}),
    ("scope: gitignored state folder still counts", with_stuffed({
        ".gitignore": ".env\nstate/\n", "state/state.json": '[{"job_id":"j1","status":"failed","attempt":1}]'}),
     {"running": True}),
    ("scope: gitignored .env is not an inline secret",
     {".gitignore": ".env\n", ".env": "API_KEY=abcdefghij0123456789\n"}, {"pass:no inline secrets": True}),
    ("scope: .env that is not ignored is still read",
     {".gitignore": "node_modules\n", ".env": "API_KEY=abcdefghij0123456789\n"}, {"fail:no inline secrets": True}),

    # Ignored Claude settings still count (field-test item F1b); nothing else under an ignored .claude/ does.
    ("scope: gitignored .claude/settings.json still counts",
     {".gitignore": ".claude/\n", ".claude/settings.json": '{"permissions": {"allow": ["Read"]}}'},
     {"pass:tool boundary": True}),
    ("scope: gitignored .claude/settings.local.json still counts",
     {".gitignore": ".claude/\n", ".claude/settings.local.json": '{"permissions": {"deny": ["Bash"]}}'},
     {"pass:tool boundary": True}),
    ("scope: other files in a gitignored .claude/ are not evidence",
     {".gitignore": ".claude/\n", ".claude/settings.json": '{"permissions": {"allow": ["Read"]}}',
      ".claude/notes.md": "human gate\n"},
     {"fail:human gate": True}),

    # The weakest hit was cited (field-test item F3). An ignore line is not a verify command.
    ("cite: .pytest_cache/ in .gitignore is not a verify command", {".gitignore": ".pytest_cache/\n"},
     {"fail:verify command": True, "fail:evidence verify": True}),
    # Guard: a comment is still evidence when nothing better matches.
    ("cite: a comment alone still counts", {"Makefile": "# each job gets its own worktree\n"},
     {"pass:work isolation": True, "pass:isolated workspace": True}),

    # Bare words with another meaning (field-test item F2). "A claim" as a statement is not a job claim.
    ("f2: a testable claim is not a job claim", {"README.md": "That is a testable claim.\n"}, {"fail:claim": True}),
    ("f2: the claim as a statement", {"README.md": "We checked the claim against the logs.\n"}, {"fail:claim": True}),
    # Guards: claiming a job, and a claim file or lock, still count.
    ("f2 ok: workers claim a job", {"README.md": "Workers claim a job before they start.\n"}, {"pass:claim": True}),
    ("f2 ok: the claim file", {"README.md": "The claim file holds the job id.\n"}, {"pass:claim": True}),
    # A method call in a code snippet in a doc is not a join (F2 join).
    ("f2: names.join in a doc snippet is not a join", {"README.md": "`names.join(', ')`\n"}, {"fail:join": True}),
    # Guard: a backticked join node still counts.
    ("f2 ok: the `join` node", {"README.md": "The `join` node merges both branches.\n"}, {"pass:join": True}),
    # A test script run directly is a verify command (field-test item F3c).
    ("verify: python test script", {"CLAUDE.md": "Tests: `python tests/test_gate.py`\n"},
     {"pass:verify command": True}),
    ("verify: node test script", {"CLAUDE.md": "Tests: `node tests/x.test.js`\n"},
     {"pass:verify command": True}),
    ("verify: bash test script", {"CLAUDE.md": "Tests: `bash tests/run.sh`\n"},
     {"pass:verify command": True}),
    # Guard: an intention to test is not a command.
    ("verify: tests some day is not a command", {"CLAUDE.md": "We should add tests some day.\n"},
     {"fail:verify command": True}),
    # An edge counts only with a condition on the line (field-test item F2, conditional edges).
    ("f2: a count of edges is not a conditional edge", {"README.md": "The graph has 3397 edges.\n"},
     {"fail:conditional edges": True}),
    ("f2: edge-cache is not an edge", {"README.md": "Edge-cache is on.\n"},
     {"fail:conditional edges": True}),
    # Guards: an edge taken on a condition still counts.
    ("f2 ok: edge on failure", {"README.md": "On failure, the edge goes back to fix.\n"},
     {"pass:conditional edges": True}),
    ("f2 ok: edges routed by status", {"README.md": "Edges from review are routed by the job status.\n"},
     {"pass:conditional edges": True}),
    # A JS timer call and "time out" as a verb are not a run budget (F2 budget).
    ("f2: setTimeout in a doc is not a budget", {"README.md": "`setTimeout(fn, 100)`\n"}, {"fail:budget": True}),
    ("f2: screenshots time out is not a budget", {"README.md": "Screenshots sometimes time out.\n"},
     {"fail:budget": True}),
    # Guards: a stated timeout, a workflow timeout and a timeout setting in code still count.
    ("f2 ok: job timeout in docs", {"README.md": "Each job has a timeout of 30 minutes.\n"}, {"pass:budget": True}),
    ("f2 ok: timeout-minutes in a workflow", {".github/workflows/ci.yml": "    timeout-minutes: 30\n"},
     {"pass:budget": True}),
    ("f2 ok: AGENT_TIMEOUT in code", {"loop.py": "AGENT_TIMEOUT = 600\n"}, {"pass:budget": True}),
]


def build(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


# -E and -P keep PYTHON* variables and the current folder out of the scorer, as -I does,
# but unlike -I they leave the user site visible, where `pip install --user pyyaml` puts it.
SCORER_FLAGS = ["-E", "-P"]


class ScorerCrash(Exception):
    """The scorer exited non-zero. Fails the case that hit it, not the whole run."""


def score(root: Path, env: dict | None = None) -> dict:
    out = subprocess.run(
        [sys.executable, *SCORER_FLAGS, str(SCORER), "--target", str(root), "--json"],
        capture_output=True, text=True, env=env,
    )
    if out.returncode != 0:
        raise ScorerCrash(f"scorer exit {out.returncode}: {out.stderr.strip()[-200:]}")
    return json.loads(out.stdout)


def check_state(data: dict, name: str) -> bool | None:
    for layer in ("harness", "loop", "graph"):
        for check in data[layer]["checks"]:
            if check["name"] == name:
                return check["ok"]
    return None


def evaluate(data: dict, expect: dict) -> list[str]:
    errors = []
    actual = {
        "final": data["composite"]["score"],
        "running": data["running"],
        "harness": data["harness"]["score"],
        "loop": data["loop"]["score"],
        "graph": data["graph"]["score"],
        "raw": data["composite"]["raw"],
        "graph_effective": data["composite"]["graph_effective"],
    }
    for key, want in expect.items():
        if key in actual:
            if actual[key] != want:
                errors.append(f"{key}: want {want}, got {actual[key]}")
            continue
        mode, check = key.split(":", 1)
        ok = check_state(data, check)
        if ok is None:
            errors.append(f"unknown check: {check}")
        elif mode == "pass" and not ok:
            errors.append(f"{check}: want pass, got fail")
        elif mode == "fail" and ok:
            errors.append(f"{check}: want fail, got pass")
    return errors


SKILL_ROOT = Path(__file__).resolve().parents[1]


class Skip(Exception):
    """The platform cannot build this fixture (for example, no symlinks)."""


def repo_under(dirname: str):
    """A repo inside a folder that is in SKIP_DIRS must still scan."""
    def run(tmp: Path) -> list[str]:
        root = tmp / dirname / "repo"
        build(root, STUFFED_FILES)
        data = score(root)
        if data["files_scanned"] == 0 or data["composite"]["score"] == 0:
            return [f"score {data['composite']['score']}, files {data['files_scanned']}"]
        return []
    return f"repo under {dirname}/", run


def installed_skill(label: str, dest_rel: str, name_line: str | None = None, only_core: bool = False):
    """Installing this skill in a repo must not change that repo's score."""
    def run(tmp: Path) -> list[str]:
        plain = tmp / "plain"
        build(plain, {"CLAUDE.md": "Ship the feature.\n"})
        base = score(plain)
        repo = tmp / "repo"
        build(repo, {"CLAUDE.md": "Ship the feature.\n"})
        dest = repo / dest_rel
        if only_core:
            for rel in ("SKILL.md", "scripts/score_setup.py", "references/rubric.md", "references/failure-modes.md"):
                build(dest, {rel: (SKILL_ROOT / rel).read_text(encoding="utf-8")})
        else:
            shutil.copytree(SKILL_ROOT, dest, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        if name_line:
            skill_md = dest / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")
            skill_md.write_text(text.replace("name: agent-graph-audit", name_line, 1), encoding="utf-8")
        data = score(repo)
        errors = []
        if data["composite"]["score"] != base["composite"]["score"] or data["files_scanned"] != 1:
            errors.append(
                f"base {base['composite']['score']}%, with skill {data['composite']['score']}%, "
                f"files {data['files_scanned']}"
            )
        if data.get("skipped_skill_dirs") != [dest_rel]:
            errors.append(f"skipped_skill_dirs {data.get('skipped_skill_dirs')}, want [{dest_rel!r}]")
        return errors
    return f"installed skill: {label}", run


def self_scan(tmp: Path) -> list[str]:
    """Scoring this skill's own folder reports it as skipped instead of scoring its docs."""
    data = score(SKILL_ROOT)
    if data["files_scanned"] != 0 or data.get("skipped_skill_dirs") != ["."]:
        return [f"files {data['files_scanned']}, skipped {data.get('skipped_skill_dirs')}"]
    return []


def symlinked_instructions(tmp: Path) -> list[str]:
    """A CLAUDE.md symlinked to a file outside the repo is still read."""
    shared = tmp / "shared"
    build(shared, {"CLAUDE.md": "definition of done: npm test passes\n"})
    repo = tmp / "repo"
    build(repo, {"README.md": "hi\n"})
    try:
        os.symlink(shared / "CLAUDE.md", repo / "CLAUDE.md")
    except (OSError, NotImplementedError):
        raise Skip("symlinks not available")
    ok = check_state(score(repo), "instruction file")
    return [] if ok else ["instruction file: want pass, got fail"]


def skill_frontmatter(tmp: Path) -> list[str]:
    """SKILL.md frontmatter has only documented keys and names no other skill (item D6)."""
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    end = text.find("\n---", 3)
    keys = {line.split(":", 1)[0] for line in text[3:end].splitlines() if line[:1].isalpha()}
    errors = []
    if keys != {"name", "description"}:
        errors.append(f"frontmatter keys {sorted(keys)}, want ['description', 'name']")
    if "harness-creator" in text:
        errors.append("SKILL.md names harness-creator")
    return errors


def run_without_yaml(root: Path, *extra: str) -> subprocess.CompletedProcess:
    """Run the scorer as if PyYAML were not installed."""
    code = (
        "import runpy, sys\n"
        "sys.modules['yaml'] = None\n"  # makes `import yaml` raise ImportError
        "sys.argv = sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    return subprocess.run([sys.executable, "-I", "-c", code, str(SCORER), "--target", str(root), *extra],
                          capture_output=True, text=True)


def yaml_missing_report(tmp: Path) -> list[str]:
    """Without PyYAML the report says the runner is unconfirmed, not both capped and 'not missing' (item D5)."""
    build(tmp, with_stuffed({".github/workflows/agent.yml": REAL_WF}))
    out = run_without_yaml(tmp)
    text = out.stdout
    errors = []
    if out.returncode != 0:
        return [f"exit {out.returncode}: {out.stderr.strip()[-200:]}"]
    if "runner check skipped: pyyaml not installed" not in text:
        errors.append("report lacks the pyyaml note")
    if "missing runner" in text:
        errors.append("report says both 'no real runner' and 'not a missing runner'")
    if "unconfirmed" not in text:
        errors.append("report does not call the runner unconfirmed")
    return errors


def yaml_missing_score(tmp: Path) -> list[str]:
    """Without PyYAML a workflow file stays fail-closed, a state file still counts, and no note without a workflow."""
    errors = []
    cases = {
        "workflow file": (with_stuffed({".github/workflows/agent.yml": REAL_WF}), False, True),
        "state file": (with_stuffed({"state.json": '[{"job_id":"j1","status":"failed","attempt":1}]'}), True, False),
        "no workflow": (STUFFED_FILES, False, False),
    }
    for label, (files, running, note) in cases.items():
        root = tmp / label.replace(" ", "-")
        build(root, files)
        out = run_without_yaml(root, "--json")
        if out.returncode != 0:
            errors.append(f"{label}: exit {out.returncode}")
            continue
        data = json.loads(out.stdout)
        if data["running"] != running or bool(data["runner_note"]) != note:
            errors.append(f"{label}: running {data['running']}, note {data['runner_note']!r}")
    return errors


def citations_computed_once(tmp: Path) -> list[str]:
    """harness_checks computes each citation once (item L5)."""
    if os.environ.get("EVAL_SCORER"):
        raise Skip("the scorer is swapped out")
    import importlib.util
    spec = importlib.util.spec_from_file_location("score_setup_probe", SCORER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = {"instruction file": 0, "verify command": 0, "secret ignore": 0}
    real_instruction, real_any, real_ignore = mod.instruction_cite, mod.cite_any, mod.gitignore_env_cite

    def instruction(files):
        calls["instruction file"] += 1
        return real_instruction(files)

    def cite_any(files, patterns):
        if patterns == [mod.VERIFY_CMD_RE.pattern]:
            calls["verify command"] += 1
        return real_any(files, patterns)

    def gitignore_env_cite(files):
        calls["secret ignore"] += 1
        return real_ignore(files)

    mod.instruction_cite, mod.cite_any, mod.gitignore_env_cite = instruction, cite_any, gitignore_env_cite
    mod.harness_checks([("CLAUDE.md", ["npm test"]), (".gitignore", [".env"])])
    return [f"{name} computed {n} times" for name, n in calls.items() if n != 1]


def crash_fails_one_case(tmp: Path) -> list[str]:
    """A scorer crash fails the cases it hits instead of aborting the run (item L4).

    Runs this file again with EVAL_SCORER pointing at a scorer that always crashes.
    The inner run must finish, report FAIL lines and a summary, and exit 1.
    """
    if os.environ.get("EVAL_SCORER"):
        raise Skip("already inside the crash check")
    crasher = tmp / "crasher.py"
    crasher.write_text("import sys\nsys.stderr.write('boom\\n')\nraise SystemExit(1)\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(Path(__file__).resolve())], capture_output=True, text=True,
                         env={**os.environ, "EVAL_SCORER": str(crasher)})
    errors = []
    if "Traceback" in out.stderr:
        errors.append("the run died with a traceback")
    if out.returncode != 1:
        errors.append(f"exit {out.returncode}, want 1")
    if "FAIL  empty:" not in out.stdout or " passed" not in out.stdout:
        errors.append("no per-case FAIL line and summary")
    return errors


def user_site_pyyaml(tmp: Path) -> list[str]:
    """PyYAML installed with `pip install --user` is visible to the scorer (item L2).

    A stub yaml module in a throwaway user site claims every file is a workflow
    with a runner. The scorer sees that only if it runs with the user site on.
    """
    home = tmp / "home"
    home.mkdir()
    # The user site follows HOME on POSIX and APPDATA on Windows. PYTHONUSERBASE would be
    # ignored by the scorer's -E, so it is dropped rather than set.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUSERBASE"}
    env.update({"HOME": str(home), "APPDATA": str(home)})
    probe = "import site; print(site.ENABLE_USER_SITE); print(site.getusersitepackages())"
    enabled, site = subprocess.run([sys.executable, *SCORER_FLAGS, "-c", probe],
                                   capture_output=True, text=True, check=True, env=env).stdout.split("\n", 1)
    site = site.strip()
    # A plain venv turns the user site off, so this Python cannot show the bug either way.
    if enabled.strip() != "True":
        raise Skip("this Python has the user site off (a plain venv); run with the system Python to test L2")
    # Never write the stub outside this case's temp folder: it would shadow the real PyYAML.
    if not Path(site).resolve().is_relative_to(tmp.resolve()):
        return [f"user site {site} is outside the eval's temp folder; stub not written"]
    build(Path(site), {"yaml.py": "def safe_load(text):\n    return {'jobs': {'x': {'runs-on': 'u'}}}\n"})
    repo = tmp / "repo"
    build(repo, {".github/workflows/x.yml": "not: a workflow\n"})
    data = score(repo, env)
    return [] if data["running"] else ["scorer did not import PyYAML from the user site"]


def citation_of(root: Path, files: dict[str, str], check: str) -> str | None:
    build(root, files)
    data = score(root)
    for layer in ("harness", "loop", "graph"):
        for c in data[layer]["checks"]:
            if c["name"] == check:
                return c["citation"]
    return None


def external_state_citation(tmp: Path) -> list[str]:
    """External state cites the job_id, status and attempt lines, not only job_id (item D4)."""
    got = citation_of(tmp, {"notes.md": "job_id is the key.\nstatus is one of a few words.\nattempt counts from 0.\n"},
                      "external state")
    want = "notes.md:1, notes.md:2, notes.md:3"
    return [] if got == want else [f"citation {got!r}, want {want!r}"]


def empty_instruction_citation(tmp: Path) -> list[str]:
    """An instruction file cites a line that exists (item D3)."""
    got = citation_of(tmp, {"CLAUDE.md": "\n\nBe careful.\n"}, "instruction file")
    return [] if got == "CLAUDE.md:3" else [f"citation {got!r}, want 'CLAUDE.md:3'"]


def out_of_scope_files(tmp: Path) -> list[str]:
    """Gitignored paths and .claude/worktrees/ copies are neither cited nor counted (item F1)."""
    build(tmp, {".gitignore": "cache/\n", "cache/notes.md": "human gate. a join node.\n",
                ".claude/worktrees/w1/CLAUDE.md": "human gate. a join node. Be careful.\n"})
    data = score(tmp)
    errors = []
    if data["files_scanned"] != 1:
        errors.append(f"files_scanned {data['files_scanned']}, want 1 (.gitignore only)")
    cited = [c["citation"] for layer in ("harness", "loop", "graph") for c in data[layer]["checks"]
             if c["citation"] and ("cache/" in c["citation"] or ".claude/worktrees/" in c["citation"])]
    if cited:
        errors.append(f"cites out-of-scope files: {cited}")
    return errors


def ignored_claude_settings(tmp: Path) -> list[str]:
    """Gitignored .claude/settings.json is read and cited; .claude/notes.md is not (item F1b)."""
    build(tmp, {".gitignore": ".claude/\n", ".claude/settings.json": '{"permissions": {"allow": ["Read"]}}',
                ".claude/notes.md": "human gate\n"})
    data = score(tmp)
    errors = []
    checks = {c["name"]: c for layer in ("harness", "loop", "graph") for c in data[layer]["checks"]}
    got = checks["tool boundary"]["citation"] or ""
    if not got.startswith(".claude/settings.json:"):
        errors.append(f"tool boundary citation {got!r}, want .claude/settings.json")
    cited = [c["citation"] for c in checks.values() if c["citation"] and ".claude/notes.md" in c["citation"]]
    if cited:
        errors.append(f"cites .claude/notes.md: {cited}")
    if data["files_scanned"] != 2:
        errors.append(f"files_scanned {data['files_scanned']}, want 2 (.gitignore, settings.json)")
    return errors


ISOLATION_RULE = "The fix node makes a fresh worktree per attempt.\n"


def best_line_cited(tmp: Path) -> list[str]:
    """Of several matching lines, the citation prefers state and config, then instruction files,
    then docs, and never a comment, an ignore line or a make target when a better line exists (item F3)."""
    cases = [
        ("verify command", {".gitignore": ".pytest_cache/\n", "CLAUDE.md": "Run pytest before you finish.\n"},
         "CLAUDE.md:1"),
        ("instruction file", {"PLAN.md": "Definition of done: the evals pass.\n", "CLAUDE.md": "Be careful.\n"},
         "CLAUDE.md:1"),
        ("external state", {"Makefile": ".PHONY: test score status\n",
                            "state/jobs.json": '[{"job_id": "j1", "status": "passed", "attempt": 1}]\n'},
         "state/jobs.json:1"),
        ("work isolation", {"Makefile": "# clean up the worktree folder\n", "README.md": ISOLATION_RULE},
         "README.md:1"),
        ("isolated workspace", {"Makefile": "# clean up the worktree folder\n", "README.md": ISOLATION_RULE},
         "README.md:1"),
        # Guard: a comment in a config file loses to a doc sentence, though config ranks above docs.
        ("work isolation", {"config/loop.yml": "# the old worktree layout\n", "README.md": ISOLATION_RULE},
         "README.md:1"),
    ]
    errors = []
    for n, (check, files, want) in enumerate(cases):
        got = citation_of(tmp / f"c{n}", files, check)
        if got != want:
            errors.append(f"{check}: citation {got!r}, want {want!r}")
    return errors


def data_json_ranks_below_docs(tmp: Path) -> list[str]:
    """Only known config files rank as config. Other .json is data and ranks below docs, and a
    permission entry in .claude/settings*.json is cited only when nothing better matches (item F3b)."""
    local_settings = '{"permissions": {"allow": [\n  "Bash(git worktree list)"\n]}}\n'
    cases = [
        ("claim", {"backup/data.json": '{"note": "claim"}\n', "README.md": "Each job is claimed by one worker.\n"},
         "README.md:1"),
        ("work isolation", {".claude/settings.local.json": local_settings,
                            "README.md": "Each job runs in its own worktree.\n"},
         "README.md:1"),
        # Guards: a known config file still ranks above docs, and data still counts when nothing else matches.
        ("claim", {"package.json": '{"description": "claim a job"}\n', "README.md": "Each job is claimed by one worker.\n"},
         "package.json:1"),
        ("claim", {"backup/data.json": '{"note": "claim"}\n'}, "backup/data.json:1"),
        ("work isolation", {".claude/settings.local.json": local_settings}, ".claude/settings.local.json:2"),
    ]
    errors = []
    for n, (check, files, want) in enumerate(cases):
        got = citation_of(tmp / f"c{n}", files, check)
        if got != want:
            errors.append(f"{check} (case {n}): citation {got!r}, want {want!r}")
    return errors


def windows_stdout_utf8(tmp: Path) -> list[str]:
    """The markdown report is UTF-8 even when stdout defaults to cp1252, as on Windows (item F7)."""
    build(tmp, {"CLAUDE.md": "Be careful.\n"})
    # Without PYTHONIOENCODING, Windows gives the scorer a cp1252 stdout; simulate that here.
    code = (
        "import io, runpy, sys\n"
        "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='cp1252', errors='strict')\n"
        "sys.argv = sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    out = subprocess.run([sys.executable, *SCORER_FLAGS, "-c", code, str(SCORER), "--target", str(tmp)],
                         capture_output=True)
    if out.returncode != 0:
        raise ScorerCrash(f"scorer exit {out.returncode}: {out.stderr.decode(errors='replace').strip()[-200:]}")
    try:
        text = out.stdout.decode("utf-8")
    except UnicodeDecodeError as why:
        return [f"stdout is not UTF-8: {why}"]
    return [] if "# Agent setup score — " in text else ["report heading with an em dash not found"]


SPECIAL = [
    *(repo_under(d) for d in ("artifacts", "build", "dist", "venv", "node_modules")),
    installed_skill("core files", ".claude/skills/agent-graph-audit", only_core=True),
    installed_skill("full copy", ".claude/skills/agent-graph-audit"),
    installed_skill("quoted name", ".claude/skills/agent-graph-audit", name_line='name: "agent-graph-audit"'),
    installed_skill("renamed copy", ".claude/skills/graph-audit-v2", name_line="name: agent-graph-audit-v2"),
    installed_skill("plugin path", ".claude/plugins/x/skills/agent-graph-audit"),
    ("self scan reports skip", self_scan),
    ("symlinked CLAUDE.md outside repo", symlinked_instructions),
    ("skill frontmatter is documented keys only", skill_frontmatter),
    ("external state cites all three fields", external_state_citation),
    ("harness citations computed once", citations_computed_once),
    ("scorer crash fails one case, not the run", crash_fails_one_case),
    ("pyyaml in the user site is visible", user_site_pyyaml),
    ("pyyaml missing: report wording", yaml_missing_report),
    ("pyyaml missing: score and note", yaml_missing_score),
    ("instruction file cites a line that exists", empty_instruction_citation),
    ("gitignored and worktree copies are not scanned", out_of_scope_files),
    ("gitignored .claude/settings.json is read and cited", ignored_claude_settings),
    ("the best matching line is cited", best_line_cited),
    ("report is UTF-8 on a cp1252 stdout", windows_stdout_utf8),
    ("data .json ranks below docs", data_json_ranks_below_docs),
]


def main() -> int:
    failed = 0
    skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, files, expect) in enumerate(CASES):
            root = Path(tmp) / f"case{i}"
            root.mkdir()
            build(root, files)
            try:
                errors = evaluate(score(root), expect)
            except ScorerCrash as why:
                errors = [str(why)]
            if errors:
                failed += 1
                print(f"FAIL  {name}: " + "; ".join(errors))
            else:
                print(f"ok    {name}")
        for i, (name, run) in enumerate(SPECIAL):
            root = Path(tmp) / f"special{i}"
            root.mkdir()
            try:
                errors = run(root)
            except Skip as why:
                skipped += 1
                print(f"skip  {name}: {why}")
                continue
            except ScorerCrash as why:
                errors = [str(why)]
            if errors:
                failed += 1
                print(f"FAIL  {name}: " + "; ".join(errors))
            else:
                print(f"ok    {name}")
    total = len(CASES) + len(SPECIAL) - skipped
    print(f"\n{total - failed}/{total} passed" + (f" ({skipped} skipped)" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
