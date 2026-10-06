# agent-graph-audit: working rules

This repo is the `agent-graph-audit` skill (SKILL.md at the root). Read `HANDOFF.md` before changing anything: it has the current status, the policy decisions already made, and the open work in order.

- Setup: Python 3.13, `pip install -r requirements.txt` (PyYAML).
- After any change, `python3 evals/run_evals.py` must stay all-pass. When you add cases, update the case count in `README.md`.
- Every bug gets a fixture first. Add a case to `evals/run_evals.py`, confirm it fails on the current code, then fix it.
- Never weaken an existing fixture to make a change pass. If a policy change really needs it, say so in the commit message and in `HANDOFF.md`.
- Fixtures are small and synthetic. Never copy content from another repo into this one, not even to reproduce a bug.
- The choices under "Decisions" in `HANDOFF.md` are deliberate. Change them only when asked.
- Verify before you claim: run the scorer or the evals and quote the result. Say when something is from reading code only.
