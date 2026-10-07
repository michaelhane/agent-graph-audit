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
import functools
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
# letter, so SECRET_KEY counts and tokenizer does not. Dutch key names count too (decision 8).
SECRET_WORDS = r"api[_-]?key|secret|token|password|api[_-]?sleutel|wachtwoord|geheim"
SECRET_KEY_PART = r"(?P<key>[A-Za-z0-9_]*(?:" + SECRET_WORDS + r")(?![a-z])[A-Za-z0-9_]*)"
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
    r"(your[_-]|[_-]here$|jouw[_-]|[_-]hier$|replace|changeme|change[_-]me|placeholder|dummy|redacted|x{6,})",
    re.I,
)
ENV_VAR_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
# A numeric cap. "max attempts" alone (no number) no longer counts, and neither does
# a counter that starts at 0 ("var attempts = 0").
ATTEMPT_NAMED = (
    r"max[_\s-]?(?:attempts|retries)(?:\s*(?:of|is|to|at)?\s*|[^\n\d]{0,20}?[:=]\s*)\d"
    r"|\bstop_after_attempt\(\s*\d"
    r"|retry(?:\s+cap)?\s*(?:of|at|<=|:)?\s*\d"
    r"|\bmax(?:imum)?\s+(?:of\s+)?\d+\s+(?:attempts|retries|tries)\b"
)
# A bare counter compared or set to a number: "while (attempts < 3)", "attempts=3".
ATTEMPT_COUNTER = r"attempt(?:s)?\s*[:=<]\s*(?!0\b)\d"
ATTEMPT_RE = re.compile(f"({ATTEMPT_NAMED}|{ATTEMPT_COUNTER})", re.I)
ATTEMPT_NAMED_RE = re.compile(f"({ATTEMPT_NAMED})", re.I)
# UI code: a bare counter there bounds a layout loop ("while (tooTall() && attempts < 12)"),
# not an agent's fix attempts (item F15). A named cap there still counts.
UI_DIRS = {"site", "web", "www", "public", "static", "frontend", "ui", "components", "assets"}


def ui_code(name: str) -> bool:
    return any(part.lower() in UI_DIRS for part in Path(name).parts[:-1])


# Code counts for the attempt cap only with agent context (item F21): a word for a job, fix,
# agent, worker or escalation near the cap (item F24), or one of those or "loop" in its path. A cap in a
# layout loop or an image generator script bounds something else.
AGENT_WORDS = r"agents?|jobs?|fix(?:es|ed|ing)?|workers?|escalat(?:e|es|ed|ing|ion)"
AGENT_TEXT_RE = re.compile(rf"(?<![a-z])(?:{AGENT_WORDS})(?![a-z])", re.I)
AGENT_PATH_RE = re.compile(rf"(?<![a-z])(?:{AGENT_WORDS}|loops?)(?![a-z])", re.I)


# The agent word has to be near the cap (item F24): "Fixed layout" in a docstring 30 lines
# above a retry cap in an image generator script is not agent context.
AGENT_NEAR = 5


def agent_lines(name: str, lines: list[str]) -> list[str] | None:
    """The file's lines near an agent word, the others blanked so citations keep their line
    numbers. All lines in an agent path; None if the file has no agent word."""
    if AGENT_PATH_RE.search(name):
        return lines
    if not AGENT_TEXT_RE.search(joined(lines)):
        return None
    keep = set()
    for i, line in enumerate(lines):
        if AGENT_TEXT_RE.search(line):
            keep.update(range(i - AGENT_NEAR, i + AGENT_NEAR + 1))
    return [line if i in keep else "" for i, line in enumerate(lines)]

# Negation. A match is negated when one of the 4 words before it, in the same
# clause, is a negator: "we do not use a worktree", "there is no allowlist".
# Dutch counts the same (decision 8): "we gebruiken geen worktree".
NEGATORS = {
    "no", "not", "never", "without", "nor", "cannot", "lack", "lacks", "lacking",
    "niet", "geen", "nooit", "zonder",
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
# non-zero counts only on a line about an exit or status ("exits non-zero",
# "a non-zero status stops the job"), not as a number ("a non-zero count").
# Dutch counts the same (decision 8): "faalt dicht", "stop bij de eerste fout",
# and its English form "stop at/on the first error/failure".
NONZERO_CONTEXT = r"\b(?:exit(?:s|ed|ing)?|return(?:s|ed|ing)?|status|code|fail(?:s|ed|ing|ure)?|abort(?:s|ed)?|stop(?:s|ped)?)\b"
FAIL_CLOSED_RE = re.compile(
    rf"(fail closed|exit code|must pass|{NONZERO_CONTEXT}.*non-zero|non-zero.*{NONZERO_CONTEXT}"
    r"|\bstop(?:s|ping)? (?:at|on) the first (?:error|failure)\b"
    r"|\bfaalt dicht\b|\bstop(?:t|pen)? bij de eerste fout\b)",
    re.I,
)
# Auto-merge in any spelling: auto-merge, auto merge, automerge, allow_auto_merge,
# platformAutomerge, enablePullRequestAutoMerge. No word boundaries around it, so
# underscores and camelCase can't hide it. Only a preceding "no " or "no-" negates;
# everything else fails closed. Also `merge ... --auto` on one logical line.
AUTO_MERGE_RE = re.compile(
    r"(?<!no )(?<!no-)auto[\s_-]?merg(?:e|ed|es|ing)|\bmerge\b.*--auto\b",
    re.I,
)
# Dutch counts the same (decision 8): "zonder akkoord", "wacht op akkoord".
GATE_PHRASES = [
    r"human gate", r"human node", r"human merge", r"no auto-merge", r"merge stays manual",
    r"\bzonder akkoord\b", r"\bwacht(?:t|en)? op akkoord\b",
]
# A review-gate config (decision 9): a config file named for a gate or review, such as
# hooks/review-gate.json, with a mode of ask or confirm. Stronger than a README sentence.
GATE_CONFIG_NAME_RE = re.compile(r"gate|review", re.I)
GATE_MODE_RE = r"""["']?\bmode["']?\s*[:=]\s*["']?(?:ask|confirm)\b"""

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


@functools.cache  # every best_cite call sorts all files by it (item F8)
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


# Lines joined for a whole-file search (item F8). The "\x00" keeps a lookahead at the end of
# a line from seeing the next line ("edge" then "computing"), and with re.M the "\n" lets "^"
# match at each line start. Any line that matches a pattern alone then also matches in the
# joined text, so a file without a match there can be skipped. Patterns may not use "$".
LINE_JOIN = "\x00\n"
_joined: dict[int, tuple[list[str], str, str | None]] = {}


def _file_texts(lines: list[str]) -> tuple[list[str], str, str | None]:
    entry = _joined.get(id(lines))
    if entry is None or entry[0] is not lines:
        text = LINE_JOIN.join(lines)
        entry = (lines, text, text.lower() if text.isascii() else None)
        _joined[id(lines)] = entry
    return entry


def joined(lines: list[str]) -> str:
    """The file's lines as one text, joined once per file and reused by every check."""
    return _file_texts(lines)[1]


def joined_lower(lines: list[str]) -> str | None:
    """The joined text lowercased, or None if it is not all ASCII.

    On ASCII text, a case-sensitive search of the lowercased text finds the same as an
    re.I search when the pattern has no uppercase letter, and it is several times faster.
    """
    return _file_texts(lines)[2]


def has_upper_literal(pattern: str) -> bool:
    """True if the pattern has an uppercase letter outside an escape such as \\S or \\B."""
    return any(c.isupper() for c in re.sub(r"\\.", "", pattern))


# A leading \b or lookbehind: zero-width, and it stops the regex engine from scanning for
# the literal that follows. The prefilter drops it, which only lets more files through.
LEADING_ASSERTIONS_RE = re.compile(r"^(?:\\b|\(\?<[!=](?:[^()\\]|\\.)*\))+")


def prefilter_pattern(pattern: str) -> str:
    """The pattern for the whole-file search: the same, minus leading zero-width assertions."""
    return LEADING_ASSERTIONS_RE.sub("", pattern)


try:
    from re import _parser as _re_parser
except ImportError:  # Python before 3.11
    import sre_parse as _re_parser
_REPEATS = {_re_parser.MAX_REPEAT, _re_parser.MIN_REPEAT, getattr(_re_parser, "POSSESSIVE_REPEAT", None)}


def _literal_sets(items) -> frozenset[str] | None:
    """Lowercase ASCII strings, one of which every match of the parsed sequence contains.

    Each literal run, mandatory group, branch and repeat with a minimum of 1 gives a candidate
    set; the most selective one (longest shortest string) wins. None if nothing is required.
    """
    candidates = []
    run = ""
    for op, av in items:
        if op == _re_parser.LITERAL and av < 128:
            run += chr(av).lower()
            continue
        if run:
            candidates.append(frozenset([run]))
            run = ""
        found = None
        if op == _re_parser.SUBPATTERN:
            found = _literal_sets(av[3])
        elif op == getattr(_re_parser, "ATOMIC_GROUP", None):
            found = _literal_sets(av)
        elif op in _REPEATS:
            if av[0] >= 1:
                found = _literal_sets(av[2])
        elif op == _re_parser.BRANCH:
            branches = [_literal_sets(b) for b in av[1]]
            if all(branches):
                found = frozenset().union(*branches)
        if found:
            candidates.append(found)
    if run:
        candidates.append(frozenset([run]))
    return max(candidates, key=lambda s: min(map(len, s)), default=None)


@functools.cache
def required_literals(pattern: str) -> frozenset[str] | None:
    """Strings, one of which is in the lowercased text of any match of pattern (item F17).

    The regex engine scans fast only for a literal at the start of a pattern. Patterns that
    start with an alternation or a lookahead are scanned slowly at every position, so a file
    is first tested for these strings with `in`. Only a necessary condition: None if unknown.
    """
    try:
        return _literal_sets(_re_parser.parse(pattern))
    except Exception:
        return None


def may_match(pattern: str, lines: list[str]) -> bool:
    """False only if no line of the file can match pattern, case-insensitively."""
    literals = required_literals(pattern)
    low = joined_lower(lines)
    if literals is None or low is None:
        return True
    return any(lit in low for lit in literals)


def best_cite(
    files: list[tuple[str, list[str]]], patterns: list[str], hit, with_next: bool = False, with_lines: bool = False
) -> str | None:
    """The best line where hit(compiled pattern, line) is true.

    With with_next, hit also gets the next line ("" after the last line).
    With with_lines, hit also gets all lines of the file and the 0-based index of the line.

    Files are tried in file_rank order, so the first strong line is the best one. A weak
    line is kept as a fallback and cited only if no strong line matches anywhere. Every
    hit needs a pattern match, so lines are only tried in files whose joined text matches.
    """
    regs = []
    for p in patterns:
        pre = prefilter_pattern(p)
        fast = None if has_upper_literal(pre) else re.compile(pre, re.M)
        regs.append((p, re.compile(p, re.I), re.compile(pre, re.I | re.M), fast))
    fallback = None
    for name, lines in sorted(files, key=lambda f: file_rank(f[0])):
        text, low = joined(lines), joined_lower(lines)
        for p, cre, whole, fast in regs:
            if not may_match(p, lines):
                continue
            if not (fast.search(low) if fast and low is not None else whole.search(text)):
                continue
            for i, line in enumerate(lines, start=1):
                if (
                    hit(cre, line, lines, i - 1)
                    if with_lines
                    else hit(cre, line, lines[i] if i < len(lines) else "")
                    if with_next
                    else hit(cre, line)
                ):
                    if not weak_line(name, line):
                        return f"{name}:{i}"
                    fallback = fallback or f"{name}:{i}"
    return fallback


def cite(files: list[tuple[str, list[str]]], pattern: str) -> str | None:
    return cite_any(files, [pattern])


def cite_any(files: list[tuple[str, list[str]]], patterns: list[str]) -> str | None:
    return best_cite(files, patterns, lambda cre, line: cre.search(line) is not None)


@functools.cache
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
# "claim they created it", "claim that it works", "claim to be first": claim as a verb about
# a statement (item F9). A subject pronoun or "to be/have" after it starts the statement.
# "claim a job", "claim it" and "claimed by" are still job claims.
CLAIM_VERB_RE = re.compile(
    r"\bclaim(?:ed)?\s+(?:that\s+)?(?:they|he|she|we|i|you)\b|\bclaim(?:ed)?\s+to\s+(?:be|have)\b",
    re.I,
)
# "Photos of the build in progress" is prose, not a job status (item F10). "In progress" counts
# only as a quoted value or on a line that talks about a status: status, state, mark, set, move, flag.
IN_PROGRESS_STATUS_RE = re.compile(
    r"[\"'`]in progress[\"'`]|\b(?:status(?:es)?|states?|mark(?:s|ed)?|sets?|mov(?:e|es|ed)|flag(?:s|ged)?)\b",
    re.I,
)


def cite_claim(files: list[tuple[str, list[str]]]) -> str | None:
    """Like cite_affirmed, but claim as a noun or verb for a statement, and "in progress"
    in plain prose, are not evidence (items F2, F9, F10)."""
    def hit(cre, line):
        if cre.pattern == "in progress" and not IN_PROGRESS_STATUS_RE.search(line):
            return False
        nouns = {m.end() for m in CLAIM_NOUN_RE.finditer(line)}
        verbs = {m.start() for m in CLAIM_VERB_RE.finditer(line)}
        return any(
            not negated(line, m.start(), m.end()) and m.end() not in nouns and m.start() not in verbs
            for m in cre.finditer(line)
        )
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


# Both secret patterns need one of these words in the key; a file without one is skipped (item F8).
SECRET_WORD_RE = re.compile(SECRET_WORDS, re.I)


def secret_hit(files: list[tuple[str, list[str]]]) -> str | None:
    for name, lines in files:
        if not may_match(SECRET_WORDS, lines) or not SECRET_WORD_RE.search(joined(lines)):
            continue
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


# An HTTP client call on the line: its timeout limits one request, not an agent run (item F20).
HTTP_CALL_RE = re.compile(
    r"\b(?:urlopen|requests\.(?:get|post|put|patch|delete|head|request)|httpx\.\w+|aiohttp\.\w+|fetch)\s*\(",
    re.I,
)
# A browser navigation or wait on a page or frame (Playwright, Puppeteer): its timeout limits that step,
# not an agent run (item F23). The receiver is required, so `asyncio.wait_for(…, timeout=600)` still counts.
BROWSER_STEP_RE = re.compile(r"\b(?:page|frame)\.(?:goto|wait_?for\w*)\s*\(", re.I)
# An agent or run context for a timeout (item F26): agent, run, job, turn or claude as a word (an `_` or
# non-letter around it is fine, so AGENT_TIMEOUT and run_agent( count), or timeout-minutes. A `.run(`
# method call (subprocess.run, asyncio.run) is not a run context.
TIMEOUT_CONTEXT_RE = re.compile(
    r"(?<![a-z])(?:agents?|runs?|running|jobs?|turns?|claude)(?![a-z])(?<!\.run)|timeout-minutes", re.I
)
# A line that ends open: the statement goes on, on the next line.
CONTINUED_RE = re.compile(r"[(\[{,\\]\s*$")


def statement_lines(lines: list[str], idx: int, limit: int = 10) -> list[str]:
    """The line at idx plus the earlier lines of its statement (lines that end in an open bracket, a comma
    or a backslash), at most limit of them."""
    start = idx
    while start > 0 and idx - start < limit and CONTINUED_RE.search(lines[start - 1]):
        start -= 1
    return lines[start : idx + 1]


def timeout_in_context(line: str, lines: list[str], idx: int) -> bool:
    """A timeout counts as a run budget only with an agent or run context in its statement (F26), and not
    on one HTTP request (F20) or one browser step (F23)."""
    if HTTP_CALL_RE.search(line) or BROWSER_STEP_RE.search(line):
        return False
    return any(TIMEOUT_CONTEXT_RE.search(s) for s in statement_lines(lines, idx))


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
    # "Budget" alone ("cognitive budget", a `budget` form field) is not a run budget: it needs an amount
    # ("budget of 30", "$5 budget", "budget: 5"), a run scope ("budget per run") or a run noun before it (F13).
    # A timeout on one HTTP request (urlopen, requests.get, httpx, fetch) limits that call, not a run (F20).
    # So does one on a browser step (page.goto, page.waitForSelector) (F23).
    # A timeout needs an agent or run context in its statement (F26): `timeout=60` on a deploy script's
    # subprocess call is not a run budget, while AGENT_TIMEOUT and timeout-minutes are.
    budget = best_cite(
        files,
        [
            r"(?<![a-z])timeout",
            r"token budget",
            r"max minutes",
            r"\bbudget\s*(?:of|is|:|=)?\s*[$€]?\d",
            r"\d\s*(?:usd|eur|dollars?|euros?)?\s+budget\b",
            r"\bbudget\s+(?:per|for each)\s+(?:run|job|attempt|turn|task|agent)\b",
            r"\b(?:run|job|turn|cost|time|step|spend|usd|dollar|compute|attempt)\s+budget\b",
            r"spend cap",
        ],
        lambda cre, line, lines, idx: (cre.pattern != r"(?<![a-z])timeout" or timeout_in_context(line, lines, idx))
        and any(not negated(line, m.start(), m.end()) for m in cre.finditer(line)),
        with_lines=True,
    )
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


# "Twice" and "stuck" count only on a line that also stops or hands off (items F2, F14):
# "It crashed twice last week." is a count and "If they're stuck, give a nudge." is
# coaching, not an exit.
EXIT_LINE = (
    r"^(?=.*\b(?:stop(?:s|ped)?|exit(?:s|ed)?|halt(?:s|ed)?|abort(?:s|ed)?|ends?|"
    r"escalat(?:e|es|ed|ion)|give(?:s)? up|park(?:s|ed)?|blocked)\b)"
)
TWICE_EXIT_RE = EXIT_LINE + r".*\btwice\b"
STUCK_EXIT_RE = EXIT_LINE + r".*\bstuck\b"


def loop_checks(files: list[tuple[str, list[str]]]) -> dict:
    # Claim, fail-closed and repeated-error are phrases. In code they only ever match
    # comments ("non-zero in the result", "Same error message"), so they read docs and config.
    prose = of_kind(files, "doc", "config")
    command = cite_any(verify_files(files), [VERIFY_CMD_RE.pattern])
    closed = cite_any(prose, [FAIL_CLOSED_RE.pattern])
    repeated = cite_any(prose, [r"same error", r"same failure", TWICE_EXIT_RE, STUCK_EXIT_RE])
    claim = cite_claim(prose)
    capped = []
    for f in files:
        if file_kind(f[0]) != "code" or not may_match(ATTEMPT_RE.pattern, f[1]):
            capped.append(f)
        elif (near := agent_lines(*f)) is not None:
            capped.append((f[0], near))
    attempt_cap = cite_affirmed([f for f in capped if not ui_code(f[0])], [ATTEMPT_RE.pattern]) or cite_affirmed(
        [f for f in capped if ui_code(f[0])], [ATTEMPT_NAMED_RE.pattern]
    )
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
        if "auto" not in joined(lines).lower():
            continue  # both spellings need "auto" (item F8)
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
    r"(?<!\d )(?<!\d)\bedges?\b(?![\s-]*cases?\b)(?!\s+computing)(?!-\w)"
)
# A status compared with a number is an HTTP or exit-code check, not a route (item F11):
# "resp.status == 200", "assert status == 401". "status == failed" still counts.
# A "=== Status ===" banner is not a comparison (item F18): "===" counts only with a
# space and a value after it, as in "status === 'failed'".
STATUS_ROUTE_RE = r"""status ==(?:=(?=\s+[a-z'"]))?(?!=)(?!\s*\d)"""
# A status comparison routes only with a routing context (items F22 and F25): the word
# edge, route, goes to, back to, next step, an arrow or a node name, on the line or on the
# next line (the branch body, as in "elif status == 'failed':" / "return 'fix'"). A branch
# word alone is not enough: "if status == 'none':" / "inbox += 1" only counts. A view
# filter "| Inbox | `status == "none"` |" is not an edge either.
STATUS_ROUTE_CONTEXT_RE = re.compile(
    r"\b(?:rout(?:e|es|ed|ing)|go(?:es)?\s+(?:back|to)|goto|back\s+to|next\s+step|edges?)\b"
    r"|->|=>|→|" + NODE_NAME_RE.pattern,
    re.I,
)
# An edge is conditional only with a condition on the same line (item F2):
# "3397 edges" or "Edge-cache is on" is not one. A number right before "edges" is a
# count and never counts, even next to a condition word (item F11).
EDGE_CONDITION_RE = re.compile(
    r"\b(?:if|when|unless|else|otherwise|conditional(?:ly)?|conditions?|depending|based on|rout(?:e|es|ed|ing))\b"
    r"|\bon\s+(?:pass|fail|failure|success|error|reject(?:ion)?|approval)\b|==",
    re.I,
)
# A workflow job that needs two or more jobs waits for both: a join.
JOIN_CONFIG_RE = r"\bneeds:\s*\[[^\]]*,"
# In config and code, only an outcome value counts, not the verb: "ignored", wontfix, not_fixable.
IGNORE_VALUE_RE = r"""["']ignored["']|\bwontfix\b|\bnot[_ -]fixable\b"""


# "Cost is bounded", "Memory is strictly bounded": the subject of "is bounded" must be a
# cycle, or nothing is said about the loop (item F2). "Retries are bounded" still counts.
BOUNDED_SUBJECT_RE = re.compile(r"\b([\w-]+)\s+(?:is|are|was|were|stays?|remains?)\s+(?:[\w-]+\s+)?bounded\b", re.I)
CYCLE_SUBJECT_RE = re.compile(r"(?:loops?|cycles?|retry|retries|attempts?|iterations?|rounds?|edges?|recursion)$", re.I)


def cite_bounded(files: list[tuple[str, list[str]]]) -> str | None:
    """Like cite_affirmed, but "X is bounded" counts only when X is a cycle (item F2)."""
    def hit(cre, line):
        other = {m.end() for m in BOUNDED_SUBJECT_RE.finditer(line) if not CYCLE_SUBJECT_RE.match(m.group(1))}
        return any(not negated(line, m.start(), m.end()) and m.end() not in other for m in cre.finditer(line))
    return best_cite(files, [r"\bbounded\b", r"retry edge", r"max attempts"], hit)


def cite_cond_edge(files: list[tuple[str, list[str]]]) -> str | None:
    """Like cite_affirmed, but the word edge counts only on a line with a condition (item F2)."""
    def hit(cre, line, nxt):
        if cre.pattern == EDGE_WORD_RE and not EDGE_CONDITION_RE.search(line):
            return False
        if cre.pattern == STATUS_ROUTE_RE and not (
                STATUS_ROUTE_CONTEXT_RE.search(line) or STATUS_ROUTE_CONTEXT_RE.search(nxt)):
            return False
        return any(not negated(line, m.start(), m.end()) for m in cre.finditer(line))
    return best_cite(files, [r"tests passed", EDGE_WORD_RE, STATUS_ROUTE_RE], hit, with_next=True)


def node_names(files: list[tuple[str, list[str]]]) -> tuple[set[str], str | None]:
    """Distinct node names, and the first line that named one.

    Docs and config: one of the eight names, on a line with an arrow or the word
    node(s), or (docs only) in backticks. Code: any name passed to add_node("...").
    """
    found: set[str] = set()
    first = None
    for name, lines in files:
        kind = file_kind(name)
        # A file that names no node, or code with no add_node( call, has no hit (item F8).
        node_re = ADD_NODE_RE if kind == "code" else NODE_NAME_RE
        if not may_match(node_re.pattern, lines) or not node_re.search(joined(lines)):
            continue
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
    gate_configs = [f for f in of_kind(files, "config") if GATE_CONFIG_NAME_RE.search(Path(f[0]).name)]
    gate_phrase = cite(gate_configs, GATE_MODE_RE) or cite_any(files, GATE_PHRASES)
    auto_merge = auto_merge_cite(files)
    if auto_merge:
        gate_why = f"Auto-merge found at {auto_merge}. Phrase check, not a permission check."
    else:
        gate_why = "A gate phrase or a review-gate config in ask/confirm mode, and no unnegated auto-merge. Phrase check, not a permission check."
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
    bounded = cite_bounded(prose) or cite(code, BOUND_CODE_RE)
    join = (
        # A method call such as names.join(', ') in a doc snippet is not a join. Neither is
        # join as becoming a member: "why join?", "join us", "join our list" (item F12), or
        # "join" with a group as its object: "join the club" (item F19).
        cite_affirmed(
            prose,
            [
                r"(?<!\.)(?<!\bwhy )\bjoin\b(?!\.\w|\(|\s+(?:us|our)\b|\s+(?:the|a|an|this|that|my|your)\s+"
                r"(?:club|community|group|team|society|association|guild|movement|crowd|ranks|cause|party"
                r"|mailing list|newsletter|waitlist|waiting list|server|discord|slack|forum|channel)\b)",
                r"wait for",
                r"partial diff",
            ],
        )
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
