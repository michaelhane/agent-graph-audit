#!/usr/bin/env python3
"""Score a repo or setup folder on harness, loop, and graph readiness.

Deterministic signals only. A high score means the artifacts exist, not that
the system is correct in production. Missing evidence scores zero.
A pass with no file:line citation is a fail, except the absence check,
which cites the scan itself.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "artifacts",
    # vendored code and tool caches: someone else's text, not this setup
    "vendor",
    "third_party",
    "site-packages",
    "target",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    "coverage",
    "htmlcov",
    ".terraform",
    ".gradle",
}
# Any folder holding this file is a Python virtual environment, whatever it is called.
VENV_MARKER = "pyvenv.cfg"

# Which kind of file a check may read. Graph checks match words only in docs and
# config; code counts for them only through graph-builder calls.
DOC_SUFFIXES = {".md", ".txt"}
CODE_SUFFIXES = {".py", ".sh", ".js", ".ts", ".mjs"}
CODE_NAMES = {"Makefile", "Dockerfile"}
# Legal boilerplate is never evidence ("LIABLE FOR ANY CLAIM" is in the MIT license).
LICENSE_STEMS = {"LICENSE", "LICENCE", "COPYING", "NOTICE"}

# State files are parsed whole: a real one is often over 200 KB, and a cut file is not valid JSON.
STATE_NAMES = {"state.json", "jobs.json", "state.jsonl", "jobs.jsonl"}
MAX_STATE_CHARS = 50_000_000
# A state file may wrap its records one level down: {"jobs": [...]}.
STATE_WRAPPER_KEYS = ("jobs", "records", "items")

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".py",
    ".sh",
    ".js",
    ".ts",
    ".mjs",
    ".env",
    ".example",
    ".gitignore",
}

# Secret check. A key name holds the keyword, and the keyword is not followed by a
# letter, so SECRET_KEY counts and tokenizer does not.
SECRET_KEY_PART = r"(?P<key>[A-Za-z0-9_]*(?:api[_-]?key|secret|token|password)(?![a-z])[A-Za-z0-9_]*)"
SECRET_VALUE = r"(?P<value>[A-Za-z0-9_\-./+=]{12,})"
# Anywhere: key, then = or : (not ==), then a quoted literal with a closing quote.
SECRET_QUOTED_RE = re.compile(
    SECRET_KEY_PART + r"""["']?\s*[:=](?!=)\s*["']""" + SECRET_VALUE + r"""["']""",
    re.I,
)
# Only in .env-style files, where every value is a literal: KEY=value with no quotes.
SECRET_BARE_RE = re.compile(
    r"^\s*(?:export\s+)?" + SECRET_KEY_PART + r"\s*=\s*" + SECRET_VALUE + r"\s*(?:#.*)?$",
    re.I,
)
# A key whose last word describes the secret rather than holding it: token_type, secret_name, tokenUrl.
NON_SECRET_KEY_ENDINGS = {
    "type", "name", "url", "uri", "path", "file", "dir", "env", "var", "count", "limit",
    "len", "length", "field", "header", "prefix", "kind", "id", "format", "mode", "style",
}
PLACEHOLDER_RE = re.compile(
    r"(your[_-]|[_-]here$|replace|changeme|change[_-]me|placeholder|dummy|redacted|x{6,})",
    re.I,
)
ENV_VAR_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
# A numeric cap. "max attempts" alone (no number) no longer counts.
ATTEMPT_RE = re.compile(
    r"(max[_\s-]?(?:attempts|retries)(?:\s*(?:of|is|to|at)?\s*|[^\n\d]{0,20}?[:=]\s*)\d"
    r"|\bstop_after_attempt\(\s*\d"
    r"|attempt(?:s)?\s*[:=<]\s*\d"
    r"|retry(?:\s+cap)?\s*(?:of|at|<=|:)?\s*\d"
    r"|\bmax(?:imum)?\s+(?:of\s+)?\d+\s+(?:attempts|retries|tries)\b)",
    re.I,
)

# Negation. A match is negated when one of the 4 words before it, in the same
# clause, is a negator: "we do not use a worktree", "there is no allowlist".
NEGATORS = {
    "no", "not", "never", "without", "nor", "cannot", "lack", "lacks", "lacking",
}
# Isolation only: "all agents share a single worktree" is the opposite of isolation,
# unless the clause also says per job / each job / its own.
SHARED_WORDS = {"share", "shares", "shared", "sharing", "single", "same"}
PER_UNIT_RE = re.compile(
    r"\b(?:per|each)\s+(?:job|task|attempt|agent|run|worker)\b|\b(?:its|their)\s+own\b", re.I
)
# After the match: "worktrees are not used", "the allowlist is disabled".
NEGATED_AFTER_RE = re.compile(
    r"^\W*(?:\w+\W+){0,2}?(?:is|are|was|were)\s+(?:not|never)\s+(?:used|enabled|set|configured|supported)\b"
    r"|^\W*(?:\w+\W+){0,2}?(?:is|are|was|were)\s+(?:disabled|unused|off)\b",
    re.I,
)
CLAUSE_BREAK_RE = re.compile(r"[.;:!?,]")
# pytest followed by a version specifier or extras is a dependency line, not a command,
# and .pytest_cache is a folder name. A test script run directly counts too:
# `python tests/test_gate.py`, `node tests/x.test.js`, `bash tests/run.sh`.
VERIFY_CMD_RE = re.compile(
    r"(npm test|\bpytest\b(?!\s*[<>=!~\[])|go test|cargo test|pnpm test|yarn test|make test"
    r"|npm run (?:lint|typecheck|test)\b"
    r"|\b(?:python3?|node|bash|sh)\s+(?:-\S+\s+)*[\w./-]*(?<![a-z])(?:tests?|spec)[\w./-]*\.(?:py|[cm]?[jt]s|sh)\b)",
    re.I,
)
FAIL_CLOSED_RE = re.compile(r"(fail closed|exit code|must pass|non-zero)", re.I)
# Auto-merge in any spelling: auto-merge, auto merge, automerge, allow_auto_merge,
# platformAutomerge, enablePullRequestAutoMerge. No word boundaries around it, so
# underscores and camelCase can't hide it. Only a preceding "no " or "no-" negates;
# everything else fails closed. Also `merge ... --auto` on one logical line.
AUTO_MERGE_RE = re.compile(
    r"(?<!no )(?<!no-)auto[\s_-]?merg(?:e|ed|es|ing)|\bmerge\b.*--auto\b",
    re.I,
)
GATE_PHRASES = [r"human gate", r"human node", r"human merge", r"no auto-merge", r"merge stays manual"]

CLAIM_CEILING = 69  # policy backstop, removed when evidence tiers ship
GRAPH_SLACK = 20  # policy: graph credit cannot exceed loop + 20


SKILL_NAME_RE = re.compile(r"""^name:\s*["']?agent-graph-audit["']?\s*$""", re.M)


def is_scanned_file(path: Path) -> bool:
    name = path.name
    if name in {".env", ".envrc"} or name.startswith(".env."):
        return True
    return path.suffix.lower() in TEXT_SUFFIXES or name in STATE_NAMES or name in {
        "AGENTS.md",
        "CLAUDE.md",
        "Makefile",
        "Dockerfile",
        ".gitignore",
    }


def names_this_skill(skill_md: Path) -> bool:
    """True if the SKILL.md frontmatter has name: agent-graph-audit, quoted or not."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="ignore")[:4000].lstrip("﻿")
    except OSError:
        return False
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    return end != -1 and SKILL_NAME_RE.search(text[3:end]) is not None


def is_this_skill(folder: Path, dirnames: list[str], filenames: list[str]) -> bool:
    """A folder is this skill by frontmatter name, or by layout (catches renamed copies)."""
    if "SKILL.md" in filenames and names_this_skill(folder / "SKILL.md"):
        return True
    if "scripts" in dirnames and "references" in dirnames:
        scorer = folder / "scripts" / "score_setup.py"
        if scorer.is_file() and (folder / "references" / "rubric.md").is_file():
            try:
                return "CLAIM_CEILING" in scorer.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return False
    return False


# Claude Code's per-session copies of the repo: the same text again, cited twice.
WORKTREE_COPIES = (".claude", "worktrees")
# Claude reads these on the machine even when .gitignore lists them (item F1b).
CLAUDE_SETTINGS = {"settings.json", "settings.local.json"}


def gitignore_rules(folder: Path, rel: str) -> list[tuple[str, str, bool, bool, bool]]:
    """Simple .gitignore rules in folder: (base, pattern, negated, dir_only, anchored).

    Not a full gitignore engine: glob patterns via fnmatch, `!`, a trailing `/`,
    and a leading or inner `/` that anchors the pattern to its folder.
    """
    try:
        text = (folder / ".gitignore").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        line = line.lstrip("!")
        if line.startswith("**/"):
            line = line[3:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        if line:
            rules.append((rel, line, negate, dir_only, anchored))
    return rules


def is_ignored(rules: list[tuple[str, str, bool, bool, bool]], rel: str, is_dir: bool) -> bool:
    """True if the last rule that matches rel (a path below root) ignores it."""
    ignored = False
    for base, pattern, negate, dir_only, anchored in rules:
        if base:
            if not rel.startswith(base + "/"):
                continue
            sub = rel[len(base) + 1:]
        else:
            sub = rel
        if dir_only and not is_dir:
            continue
        if fnmatch.fnmatchcase(sub if anchored else sub.rsplit("/", 1)[-1], pattern):
            ignored = not negate
    return ignored


def iter_files(root: Path, skipped: list[str] | None = None):
    """Yield scanned files under root.

    One top-down walk. SKIP_DIRS, .claude/worktrees/ and copies of this skill are
    pruned before they are entered, and only names below root are tested, so a
    repo that lives inside a folder called build/ still scans. Paths a .gitignore
    at or below root ignores are not read, except state files (real loops often
    ignore their state folder) and .claude/settings*.json (Claude still reads
    them). Symlinked files are read; symlinked folders are not followed.
    """
    if root.is_file():
        yield root
        return
    rules_at: dict[str, list] = {}
    ignored_dirs: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        folder = Path(dirpath)
        if folder != root and VENV_MARKER in filenames:
            dirnames[:] = []  # a virtual environment, whatever its name
            continue
        if is_this_skill(folder, dirnames, filenames):
            if skipped is not None:
                rel = folder.relative_to(root).as_posix()
                skipped.append(rel if rel != "." else ".")
            dirnames[:] = []
            continue
        rel = folder.relative_to(root).as_posix()
        rel = "" if rel == "." else rel
        rules = rules_at.get(rel, [])
        if ".gitignore" in filenames:
            rules = rules + gitignore_rules(folder, rel)
        in_ignored = rel in ignored_dirs
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and (folder.name, d) != WORKTREE_COPIES
        )
        # Ignored folders are still walked, but only their state files are read.
        for d in dirnames:
            sub = f"{rel}/{d}" if rel else d
            rules_at[sub] = rules
            if in_ignored or is_ignored(rules, sub, True):
                ignored_dirs.add(sub)
        for fname in sorted(filenames):
            path = folder / fname
            if path.name.split(".")[0].upper() in LICENSE_STEMS:
                continue
            file_rel = f"{rel}/{fname}" if rel else fname
            kept = fname in STATE_NAMES or (folder.name == ".claude" and fname in CLAUDE_SETTINGS)
            if not kept and (in_ignored or is_ignored(rules, file_rel, False)):
                continue
            if is_scanned_file(path) and path.is_file():
                yield path


def read_files(root: Path, skipped: list[str] | None = None) -> list[tuple[str, list[str]]]:
    files = []
    for path in iter_files(root, skipped):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        limit = MAX_STATE_CHARS if path.name in STATE_NAMES else 200_000
        if len(text) > limit:
            text = text[:limit]
        rel = (path.relative_to(root) if path != root else Path(path.name)).as_posix()
        files.append((rel, text.splitlines()))
    return files


INSTRUCTION_NAMES = {"AGENTS.md", "CLAUDE.md"}
# A make target or .PHONY line: `.PHONY: test status`, `test: build`. Not `CC := gcc`.
MAKE_TARGET_RE = re.compile(r"^[^\s#=:][^=:]*::?(?!=)")


CONFIG_NAMES = {"Makefile", "package.json"}
# Claude settings and hook configs are the only other .json that ranks as config.
CONFIG_JSON_RE = re.compile(r"(?:.*/)?(?:\.claude/settings(?:\.local)?|hooks[^/]*)\.json")
# A tool-rule entry in a permission list: "Bash(git worktree list)",
PERMISSION_ENTRY_RE = re.compile(r'^\s*"\w+\(.*\)"\s*,?\s*$')


def file_rank(name: str) -> int:
    """Which file to cite first when several match: state, config, instruction files, docs, code, data.

    Only known config files rank as config. Any other .json is data (a backup, a stored
    snippet) and ranks last, though it still counts when nothing else matches.
    """
    path = Path(name)
    if path.name in STATE_NAMES:
        return 0
    if path.name in CONFIG_NAMES or CONFIG_JSON_RE.fullmatch(name):
        return 1
    if path.name in INSTRUCTION_NAMES:
        return 2
    if path.suffix.lower() == ".json":
        return 5
    return {"config": 1, "doc": 3, "code": 4}[file_kind(name)]


def weak_line(name: str, line: str) -> bool:
    """A comment, an ignore-file line, a make target or a permission entry: cited only when
    no better line matches. A permission entry allows a command; it does not state a rule."""
    path = Path(name)
    if path.name == ".gitignore":
        return True
    if path.suffix.lower() == ".json" and PERMISSION_ENTRY_RE.match(line):
        return True
    stripped = line.lstrip()
    if file_kind(name) == "doc":
        return stripped.startswith("<!--")  # a Markdown "#" is a heading, not a comment
    if stripped.startswith(("#", "//")):
        return True
    return path.name == "Makefile" and MAKE_TARGET_RE.match(line) is not None


def best_cite(files: list[tuple[str, list[str]]], patterns: list[str], hit) -> str | None:
    """The best line where hit(compiled pattern, line) is true.

    Files are tried in file_rank order, so the first strong line is the best one. A weak
    line is kept as a fallback and cited only if no strong line matches anywhere.
    """
    regs = [re.compile(p, re.I) for p in patterns]
    fallback = None
    for name, lines in sorted(files, key=lambda f: file_rank(f[0])):
        for cre in regs:
            for i, line in enumerate(lines, start=1):
                if hit(cre, line):
                    if not weak_line(name, line):
                        return f"{name}:{i}"
                    fallback = fallback or f"{name}:{i}"
    return fallback


def cite(files: list[tuple[str, list[str]]], pattern: str) -> str | None:
    return cite_any(files, [pattern])


def cite_any(files: list[tuple[str, list[str]]], patterns: list[str]) -> str | None:
    return best_cite(files, patterns, lambda cre, line: cre.search(line) is not None)


def file_kind(name: str) -> str:
    path = Path(name)
    suffix = path.suffix.lower()
    if suffix in DOC_SUFFIXES:
        return "doc"
    if suffix in CODE_SUFFIXES or path.name in CODE_NAMES:
        return "code"
    return "config"


def of_kind(files: list[tuple[str, list[str]]], *kinds: str) -> list[tuple[str, list[str]]]:
    return [f for f in files if file_kind(f[0]) in kinds]


def negated(text: str, start: int, end: int, shared_words: bool = False) -> bool:
    """True if the match at text[start:end] is negated within its clause."""
    left = 0
    for brk in CLAUSE_BREAK_RE.finditer(text, 0, start):
        left = brk.end()
    nxt = CLAUSE_BREAK_RE.search(text, end)
    right = nxt.start() if nxt else len(text)
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", text[left:start])][-4:]
    if any(w in NEGATORS or w.endswith("n't") for w in words):
        return True
    if NEGATED_AFTER_RE.search(text[end:right]):
        return True
    if shared_words and any(w in SHARED_WORDS for w in words):
        return PER_UNIT_RE.search(text[left:right]) is None
    return False


def cite_affirmed(
    files: list[tuple[str, list[str]]], patterns: list[str], shared_words: bool = False
) -> str | None:
    """Like cite_any, but a negated mention is not evidence. Keeps looking for one that isn't."""
    return best_cite(
        files,
        patterns,
        lambda cre, line: any(not negated(line, m.start(), m.end(), shared_words) for m in cre.finditer(line)),
    )


CLAIM_PATTERNS = [r"(?<!any )\bclaim(?:ed)?\b", r"in progress", r"lock file", r"already taken"]
# "a testable claim", "the claim": claim as a statement, not a job being claimed.
# A claim file, lock or step is still a job claim.
CLAIM_NOUN_RE = re.compile(
    r"\b(?:a|an|the|this|that|these|those|its|their|our|your|my|his|her)\s+(?:[\w-]+\s+)?claim\b"
    r"(?!\s+(?:file|lock|step|node|record|marker|token)s?\b)",
    re.I,
)


def cite_claim(files: list[tuple[str, list[str]]]) -> str | None:
    """Like cite_affirmed, but claim used as a noun for a statement is not evidence (item F2)."""
    def hit(cre, line):
        nouns = {m.end() for m in CLAIM_NOUN_RE.finditer(line)}
        return any(not negated(line, m.start(), m.end()) and m.end() not in nouns for m in cre.finditer(line))
    return best_cite(files, CLAIM_PATTERNS, hit)


def verify_files(files: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    """Files that may hold a verify command: requirements files only list dependencies, .gitignore only paths."""
    return [
        f for f in files
        if not re.match(r"requirements.*\.txt$", Path(f[0]).name, re.I) and Path(f[0]).name != ".gitignore"
    ]


# A non-empty allow or deny list in Claude Code settings is a tool boundary.
PERMISSION_LIST_RE = re.compile(r'"(?:allow|deny)"\s*:\s*\[\s*"')


def permissions_cite(files: list[tuple[str, list[str]]]) -> str | None:
    for name, lines in files:
        if not re.fullmatch(r"(?:.*/)?\.claude/settings(?:\.local)?\.json", name):
            continue
        # The list may start on a later line than its key, so test the joined text.
        text = "\n".join(lines)
        m = PERMISSION_LIST_RE.search(text)
        if m:
            return f"{name}:{text.count(chr(10), 0, m.start()) + 1}"
    return None


# A .gitignore line that ignores a file named .env: .env, /.env, **/.env, .env*, *.env.
ENV_IGNORE_RE = re.compile(r"^(?:/|\*\*/)?(?:\*)?\.env\*?$")


def gitignore_env_cite(files: list[tuple[str, list[str]]]) -> str | None:
    """Line in a .gitignore that ignores .env itself. Comments, un-ignores and .envrc don't count."""
    for name, lines in files:
        if Path(name).name != ".gitignore":
            continue
        for i, line in enumerate(lines, start=1):
            if ENV_IGNORE_RE.match(line.strip()):
                return f"{name}:{i}"
    return None


def instruction_cite(files: list[tuple[str, list[str]]]) -> str | None:
    """CLAUDE.md/AGENTS.md first (its definition of done, else its first line), then a definition of done elsewhere."""
    instructions = [f for f in files if re.search(r"(AGENTS|CLAUDE)\.md$", f[0])]
    found = cite(instructions, r"definition of done")
    if found:
        return found
    for name, lines in instructions:
        for i, line in enumerate(lines, start=1):
            if line.strip():
                return f"{name}:{i}"  # an empty file is not an instruction file
    return cite(files, r"definition of done")


def score_checks(checks: list[tuple[str, int, bool, str, str | None, int | None]]) -> dict:
    scored = []
    earned = 0
    total = 0
    for name, weight, ok, why, citation, award in checks:
        total += weight
        if ok and not citation:
            ok = False
            why = why + " (no citation, counted as fail)"
        given = 0
        if ok:
            given = weight if award is None else award
            earned += given
        scored.append(
            {
                "name": name,
                "points": weight,
                "awarded": given,
                "ok": ok,
                "why": why,
                "citation": citation,
            }
        )
    return {
        "score": round(100 * earned / total) if total else 0,
        "earned": earned,
        "total": total,
        "present": [c["name"] for c in scored if c["ok"]],
        "missing": [c["name"] for c in scored if not c["ok"]],
        "checks": scored,
    }


def is_env_file(name: str) -> bool:
    base = Path(name).name
    return base in {".env", ".envrc"} or base.startswith(".env.") or base.endswith(".env")


def key_last_word(key: str) -> str:
    words = []
    for part in re.split(r"[_\-]+", key):
        words += re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", part)
    return words[-1].lower() if words else ""


def not_a_secret(key: str, value: str) -> bool:
    """Key/value pairs that look like a secret by shape but are not one."""
    if key_last_word(key) in NON_SECRET_KEY_ENDINGS:
        return True  # token_type = "unstructured" describes a token, it isn't one
    if value.startswith(("/", ".")):
        return True  # a file path
    if value.lower().startswith("example"):
        return True  # prefix only: AWS's documented example key ends in EXAMPLEKEY and must still fail
    if ENV_VAR_NAME_RE.match(value):
        return True  # names an environment variable, e.g. "OPENAI_API_KEY"
    return PLACEHOLDER_RE.search(value) is not None


def secret_hit(files: list[tuple[str, list[str]]]) -> str | None:
    for name, lines in files:
        env_file = is_env_file(name)
        for i, line in enumerate(lines, start=1):
            pairs = [(m["key"], m["value"]) for m in SECRET_QUOTED_RE.finditer(line)]
            if env_file:
                bare = SECRET_BARE_RE.match(line)
                if bare:
                    pairs.append((bare["key"], bare["value"]))
            if any(not not_a_secret(k, v) for k, v in pairs):
                return f"{name}:{i}"
    return None


def harness_checks(files: list[tuple[str, list[str]]]) -> dict:
    found = secret_hit(files)
    instruction = instruction_cite(files)
    verify = cite_any(verify_files(files), [VERIFY_CMD_RE.pattern])
    secret_ignore = gitignore_env_cite(files)
    scanned = len(files) > 0
    secret_ok = scanned and found is None
    secret_cite = f"scanned:{len(files)}" if secret_ok else found
    isolation = cite_affirmed(files, [r"worktree", r"branch per", r"isolated branch"], shared_words=True)
    boundary = cite_affirmed(files, [r"allowlist", r"protected path", r"cannot merge", r"cannot push"]) or permissions_cite(
        files
    )
    # "Trace the bug back": trace as a verb with an object or "back/down" is debugging, not a record of runs (F2).
    trace = cite_affirmed(
        files,
        [
            r"\btrace\b(?!\s+(?:the|a|an|this|that|these|those|it|its|them|their|our|your|back|down)\b)",
            r"audit log",
            r"tool call",
            r"run log",
        ],
    )
    # A letter before "timeout" makes it a call or field name (setTimeout, clearTimeout), not a run budget (F2).
    budget = cite_affirmed(files, [r"(?<![a-z])timeout", r"token budget", r"max minutes", r"\bbudget\b", r"spend cap"])
    checks = [
        (
            "instruction file",
            15,
            instruction is not None,
            "AGENTS.md or CLAUDE.md, or an explicit definition of done",
            instruction,
            None,
        ),
        (
            "verify command",
            15,
            verify is not None,
            "A named test, lint, or typecheck command",
            verify,
            None,
        ),
        (
            "secret ignore",
            10,
            secret_ignore is not None,
            "A .gitignore line that ignores .env itself",
            secret_ignore,
            None,
        ),
        (
            "no inline secrets",
            10,
            secret_ok,
            "Scan ran and found no key=literal assignments" if secret_ok else "No scan, or a literal secret was found",
            secret_cite,
            None,
        ),
        (
            "work isolation",
            10,
            isolation is not None,
            "Worktree or branch-per-job, not negated or shared",
            isolation,
            None,
        ),
        (
            "tool boundary",
            15,
            boundary is not None,
            "Tool or path boundary, not negated",
            boundary,
            None,
        ),
        (
            "trace",
            15,
            trace is not None,
            "A place runs are recorded, not negated",
            trace,
            None,
        ),
        (
            "budget",
            10,
            budget is not None,
            "Timeout or spend cap, not negated",
            budget,
            None,
        ),
    ]
    return score_checks(checks)


# "Twice" counts only on a line that also stops or hands off (item F2):
# "It crashed twice last week." is a count, not an exit.
TWICE_EXIT_RE = (
    r"^(?=.*\b(?:stop(?:s|ped)?|exit(?:s|ed)?|halt(?:s|ed)?|abort(?:s|ed)?|ends?|"
    r"escalat(?:e|es|ed|ion)|give(?:s)? up|park(?:s|ed)?|blocked)\b).*\btwice\b"
)


def loop_checks(files: list[tuple[str, list[str]]]) -> dict:
    # Claim, fail-closed and repeated-error are phrases. In code they only ever match
    # comments ("non-zero in the result", "Same error message"), so they read docs and config.
    prose = of_kind(files, "doc", "config")
    command = cite_any(verify_files(files), [VERIFY_CMD_RE.pattern])
    closed = cite_any(prose, [FAIL_CLOSED_RE.pattern])
    repeated = cite_any(prose, [r"same error", r"same failure", TWICE_EXIT_RE, r"\bstuck\b"])
    claim = cite_claim(prose)
    attempt_cap = cite_affirmed(files, [ATTEMPT_RE.pattern])
    workspace = cite_affirmed(files, [r"worktree", r"per job"], shared_words=True)
    checks = [
        (
            "claim",
            15,
            claim is not None,
            "A job is claimed so a second loop cannot take it",
            claim,
            None,
        ),
        (
            "attempt cap",
            20,
            attempt_cap is not None,
            "Numeric retry or attempt cap, not negated",
            attempt_cap,
            None,
        ),
        (
            "evidence verify",
            20,
            command is not None and closed is not None,
            "A real test command plus a separate fail-closed phrase",
            command if command and closed else None,
            None,
        ),
        (
            "fail closed",
            15,
            closed is not None,
            "Failure stops or escalates",
            closed,
            None,
        ),
        (
            "repeated error exit",
            15,
            repeated is not None,
            "Same error twice is an exit. Half credit until a fingerprint exists.",
            repeated,
            7,
        ),
        (
            "isolated workspace",
            15,
            workspace is not None,
            "Each attempt has its own tree, not negated or shared",
            workspace,
            None,
        ),
    ]
    return score_checks(checks)


def logical_lines(lines: list[str]):
    """Yield (first line number, text), joining lines that end in a backslash.

    A shell command split as `gh pr merge "$PR" \\` + `--auto` is checked as one line.
    """
    start = None
    parts: list[str] = []
    for i, line in enumerate(lines, start=1):
        if start is None:
            start = i
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            parts.append(stripped[:-1])
            continue
        parts.append(line)
        yield start, " ".join(parts)
        start, parts = None, []
    if parts:
        yield start, " ".join(parts)


def auto_merge_cite(files: list[tuple[str, list[str]]]) -> str | None:
    for name, lines in files:
        for i, text in logical_lines(lines):
            if AUTO_MERGE_RE.search(text):
                return f"{name}:{i}"
    return None


NODE_NAME_RE = re.compile(r"\b(intake|triage|fix|review|gate|planner|executor|verifier)\b", re.I)
# A node name counts only next to graph context: an arrow, or the word node(s).
# "Node.js", "node_modules" and "Node 20" are not graph context.
NODE_CONTEXT_RE = re.compile(r"->|→|=>|⇒|\bnodes?\b(?!\.js|_modules|\s*\d)", re.I)
# Graph-builder calls in code (LangGraph style).
ADD_NODE_RE = re.compile(r"""\badd_node\(\s*["']([\w-]+)["']""")
COND_EDGE_CODE_RE = r"\badd_conditional_edges\("
JOIN_CODE_RE = r"\badd_edge\(\s*\["  # add_edge(["a", "b"], "c"): c waits for a and b
# A cycle bound in code: LangGraph's recursion_limit, or a numeric max_attempts/retries/iterations.
BOUND_CODE_RE = r"\brecursion_limit\b[^\n\d]{0,20}?\d|\bmax_(?:attempts|retries|iterations)\b[^\n\d]{0,20}?[:=]\s*\d"
# "edge cases", "cutting edge" and friends are not graph edges.
EDGE_WORD_RE = (
    r"(?<!cutting )(?<!leading )(?<!bleeding )(?<!microsoft )"
    r"\bedges?\b(?![\s-]*cases?\b)(?!\s+computing)(?!-\w)"
)
# An edge is conditional only with a condition on the same line (item F2):
# "3397 edges" or "Edge-cache is on" is not one.
EDGE_CONDITION_RE = re.compile(
    r"\b(?:if|when|unless|else|otherwise|conditional(?:ly)?|conditions?|depending|based on|rout(?:e|es|ed|ing))\b"
    r"|\bon\s+(?:pass|fail|failure|success|error|reject(?:ion)?|approval)\b|==",
    re.I,
)
# A workflow job that needs two or more jobs waits for both: a join.
JOIN_CONFIG_RE = r"\bneeds:\s*\[[^\]]*,"
# In config and code, only an outcome value counts, not the verb: "ignored", wontfix, not_fixable.
IGNORE_VALUE_RE = r"""["']ignored["']|\bwontfix\b|\bnot[_ -]fixable\b"""


def cite_cond_edge(files: list[tuple[str, list[str]]]) -> str | None:
    """Like cite_affirmed, but the word edge counts only on a line with a condition (item F2)."""
    def hit(cre, line):
        if cre.pattern == EDGE_WORD_RE and not EDGE_CONDITION_RE.search(line):
            return False
        return any(not negated(line, m.start(), m.end()) for m in cre.finditer(line))
    return best_cite(files, [r"tests passed", EDGE_WORD_RE, r"status =="], hit)


def node_names(files: list[tuple[str, list[str]]]) -> tuple[set[str], str | None]:
    """Distinct node names, and the first line that named one.

    Docs and config: one of the eight names, on a line with an arrow or the word
    node(s), or (docs only) in backticks. Code: any name passed to add_node("...").
    """
    found: set[str] = set()
    first = None
    for name, lines in files:
        kind = file_kind(name)
        for i, line in enumerate(lines, start=1):
            if kind == "code":
                hits = {m.group(1).lower() for m in ADD_NODE_RE.finditer(line)}
            else:
                context = NODE_CONTEXT_RE.search(line) is not None
                hits = set()
                for m in NODE_NAME_RE.finditer(line):
                    ticked = (
                        kind == "doc"
                        and line[m.start() - 1 : m.start()] == "`"
                        and line[m.end() : m.end() + 1] == "`"
                    )
                    if context or ticked:
                        hits.add(m.group(1).lower())
            if hits:
                found |= hits
                first = first or f"{name}:{i}"
    return found, first


def external_state_cite(files: list[tuple[str, list[str]]]) -> str | None:
    """Citations for job_id, status and attempt, all three required."""
    cites = [cite(files, p) for p in (r"job_id", r"\bstatus\b", r"\battempt\b")]
    if any(c is None for c in cites):
        return None
    return ", ".join(dict.fromkeys(cites))


def graph_checks(files: list[tuple[str, list[str]]]) -> dict:
    gate_phrase = cite_any(files, GATE_PHRASES)
    auto_merge = auto_merge_cite(files)
    if auto_merge:
        gate_why = f"Auto-merge found at {auto_merge}. Phrase check, not a permission check."
    else:
        gate_why = "A gate phrase, and no unnegated auto-merge. Phrase check, not a permission check."
    found, node_cite = node_names(files)
    prose = of_kind(files, "doc", "config")
    docs = of_kind(files, "doc")
    config = of_kind(files, "config")
    code = of_kind(files, "code")
    edges = cite_cond_edge(prose) or cite(code, COND_EDGE_CODE_RE)
    # A command or flag (`git check-ignore`, `--ignore=tests/slow`) is not an ignore outcome.
    ignore = cite_affirmed(docs, [r"(?<![-\w])ignore\b(?![-=])", r"wontfix", r"won't fix", r"not fixable"]) or cite_any(
        config + code, [IGNORE_VALUE_RE]
    )
    bounded = cite_affirmed(prose, [r"\bbounded\b", r"retry edge", r"max attempts"]) or cite(code, BOUND_CODE_RE)
    join = (
        # A method call such as names.join(', ') in a doc snippet is not a join.
        cite_affirmed(prose, [r"(?<!\.)\bjoin\b(?!\.\w|\()", r"wait for", r"partial diff"])
        or cite(config, JOIN_CONFIG_RE)
        or cite(code, JOIN_CODE_RE)
    )
    state_cite = external_state_cite(files)
    checks = [
        (
            "named nodes",
            20,
            len(found) >= 3,
            "At least three distinct node names in graph context (arrow, the word node, backticks, or add_node)",
            node_cite if len(found) >= 3 else None,
            None,
        ),
        (
            "conditional edges",
            15,
            edges is not None,
            "An edge with a condition (docs or config), or add_conditional_edges (code)",
            edges,
            None,
        ),
        (
            "external state",
            20,
            state_cite is not None,
            "job id, status, and attempt stored outside the chat",
            state_cite,
            None,
        ),
        (
            "human gate",
            15,
            gate_phrase is not None and auto_merge is None,
            gate_why,
            gate_phrase if auto_merge is None else None,
            None,
        ),
        (
            "ignore outcome",
            10,
            ignore is not None,
            "The graph can refuse a job: ignore/wontfix in docs, or an 'ignored' outcome value in config or code",
            ignore,
            None,
        ),
        (
            "bounded cycle",
            10,
            bounded is not None,
            "Cycles have a counter: bounded/max attempts in docs or config (not negated, not 'unbounded'), or recursion_limit / max_attempts = N in code",
            bounded,
            None,
        ),
        (
            "join",
            10,
            join is not None,
            "A node can wait for siblings: join/wait for in docs or config, needs: [a, b], or add_edge([a, b], c)",
            join,
            None,
        ),
    ]
    return score_checks(checks)


STATUSES = {"open", "claimed", "in_progress", "running", "passed", "failed", "ignored", "escalated", "done"}


def state_record_ok(node, wrapped: bool = False) -> bool:
    if isinstance(node, list):
        return any(state_record_ok(item, wrapped) for item in node)
    if not isinstance(node, dict):
        return False
    if not wrapped:
        for key in STATE_WRAPPER_KEYS:
            inner = node.get(key)
            if isinstance(inner, list) and state_record_ok(inner, True):
                return True
    job_id = node.get("job_id")
    status = node.get("status")
    attempt = node.get("attempt")
    if not isinstance(job_id, str) or not job_id.strip():
        return False
    if not isinstance(status, str) or status not in STATUSES:
        return False
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        return False
    return True


def state_file_ready(files: list[tuple[str, list[str]]]) -> bool:
    for fname, lines in files:
        if Path(fname).name not in STATE_NAMES:
            continue
        raw = "\n".join(lines).strip()
        if not raw:
            continue
        try:
            if fname.endswith(".jsonl"):
                data = [json.loads(line) for line in lines if line.strip()]
            else:
                data = json.loads(raw)
            if state_record_ok(data):
                return True
        except (ValueError, RecursionError):  # JSONDecodeError is a ValueError
            continue
    return False


def workflow_files(files: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    """GitHub Actions only: .github/workflows/* and files named workflow.yml/.yaml.

    GitLab CI, CircleCI and LangGraph projects are not recognised as runners.
    """
    found = []
    for item in files:
        fname = item[0]
        lowered = fname.replace("\\", "/").lower()
        if (
            ".github/workflows/" in lowered
            or lowered.endswith("workflow.yml")
            or lowered.endswith("workflow.yaml")
        ):
            found.append(item)
    return found


def workflow_ready(files: list[tuple[str, list[str]]]) -> tuple[bool, str | None]:
    candidates = workflow_files(files)
    if not candidates:
        return False, None
    try:
        import yaml
    except ImportError:
        return False, "runner check skipped: pyyaml not installed"
    for fname, lines in candidates:
        text = "\n".join(lines)
        try:
            parsed = yaml.safe_load(text)
        except Exception:
            continue
        jobs = parsed.get("jobs") if isinstance(parsed, dict) else None
        if not isinstance(jobs, dict) or not jobs:
            continue
        for job in jobs.values():
            if isinstance(job, dict) and (job.get("runs-on") or job.get("steps")):
                return True, None
    return False, None


def runner_status(files: list[tuple[str, list[str]]]) -> tuple[bool, str | None]:
    if state_file_ready(files):
        return True, None
    return workflow_ready(files)


def composite(harness: int, loop: int, graph: int, running: bool) -> dict:
    graph_effective = min(graph, loop + GRAPH_SLACK)
    raw = round(0.3 * harness + 0.4 * loop + 0.3 * graph_effective)
    caps = []
    score = raw
    if harness < 40:
        score = min(score, 49)
        caps.append("policy: harness under 40 caps the composite at 49")
    if not running:
        score = min(score, CLAIM_CEILING)
        caps.append("policy: no real runner or state file caps the composite at 69 until evidence tiers ship")
    return {
        "score": score,
        "raw": raw,
        "graph_effective": graph_effective,
        "cap": "; ".join(caps) if caps else None,
        "weights": {"harness": 0.3, "loop": 0.4, "graph": 0.3},
        "policy": {
            "weights": "policy, not a measurement",
            "graph_slack": GRAPH_SLACK,
            "claim_ceiling": CLAIM_CEILING,
            "harness_floor_cap": 49,
        },
    }


def report(target: Path) -> dict:
    skipped: list[str] = []
    files = read_files(target, skipped)
    running, runner_note = runner_status(files)
    h = harness_checks(files)
    l = loop_checks(files)
    g = graph_checks(files)
    c = composite(h["score"], l["score"], g["score"], running)
    return {
        "target": str(target),
        "files_scanned": len(files),
        "skipped_skill_dirs": skipped,
        "running": running,
        "runner_note": runner_note,
        "harness": h,
        "loop": l,
        "graph": g,
        "composite": c,
    }


def render(data: dict) -> str:
    lines = [
        f"# Agent setup score — {data['composite']['score']}%",
        "",
        f"Target: `{data['target']}` · files scanned: {data['files_scanned']}",
        "",
        "| Layer | Score | Missing |",
        "|---|---:|---|",
    ]
    for key in ("harness", "loop", "graph"):
        missing = ", ".join(data[key]["missing"]) or "—"
        lines.append(f"| {key} | {data[key]['score']}% | {missing} |")
    cap = data["composite"]["cap"] or "none"
    lines.append("")
    lines.append(
        f"Composite {data['composite']['score']}% (raw {data['composite']['raw']}%, graph credit {data['composite']['graph_effective']}). Cap: {cap}."
    )
    lines.append("")
    lines.append(
        "Policy, not measurements: weights 30/40/30, graph credit <= loop + 20, claim ceiling 69."
    )
    lines.append("")
    if data.get("runner_note"):
        lines.append(
            data["runner_note"]
            + ". A workflow file was found but not parsed, so the runner is unconfirmed and the score stays"
            " fail-closed. Install pyyaml and run again."
        )
    elif data.get("running"):
        lines.append("Runner or state file found. A plain CI job still counts. Tiers will require the workflow to reference the loop.")
    else:
        lines.append("No workflow runner or state file found. Treat node names as a claim, not a running graph.")
    skipped = data.get("skipped_skill_dirs") or []
    if skipped:
        lines.append("")
        if "." in skipped:
            lines.append("Skipped: the target is this skill itself, so there is nothing of yours to score.")
        else:
            lines.append("Skipped (this skill's own files, so they don't inflate the score): " + ", ".join(skipped))
    lines.append("")
    lines.append("## Citations")
    for key in ("harness", "loop", "graph"):
        for check in data[key]["checks"]:
            if check["ok"]:
                lines.append(f"- {key} / {check['name']}: {check['citation']}")
    lines.append("")
    lines.append("## Next gap")
    order = sorted(("harness", "loop", "graph"), key=lambda k: data[k]["score"])
    weakest = order[0]
    missing = data[weakest]["missing"]
    if missing:
        lines.append(f"Weakest layer is {weakest} at {data[weakest]['score']}%. Add: {missing[0]}.")
    else:
        lines.append("No missing checks. Re-read traces before raising autonomy.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score harness, loop, and graph setup")
    parser.add_argument("--target", required=True, help="Repo or folder to scan")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    args = parser.parse_args()
    # Windows writes stdout as cp1252 by default, which turns the report's "—" into byte 0x97.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"target not found: {target}", file=sys.stderr)
        return 2
    data = report(target)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
