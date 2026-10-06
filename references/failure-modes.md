---
description: "Failure modes that should lower or qualify a score. Read when the scan looks healthy but the setup is still unsafe."
connections: [rubric]
---

# Failure modes

| Pattern | What to say |
|---|---|
| Verifier theater | The agent writes a new test that passes. Credit verify only if the original command is the gate. |
| Graph cosplay | Nodes exist in a slide or README and nowhere executable. Score the claim, then say it is not running. |
| Shared dirty tree | Describing a shared dirty tree does not pass, and neither does "all agents share a single worktree" or "we do not use a worktree". Isolation passes on worktree, branch per, isolated branch, or per job, when the sentence affirms it. |
| Unbounded retry | No numeric cap. Attempt-cap check fails. "Unbounded" and "no max attempts" fail bounded cycle too. |
| Hidden approval | Fails if the merge is described in a detected phrase. The scorer cannot see merge permissions. |
| No owner | Audit exists, no person named. Mention it even if the points passed. |
