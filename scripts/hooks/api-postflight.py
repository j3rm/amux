#!/usr/bin/env python3
"""PostToolUse hook — record when the agent read a skill or fetched vendor docs.

Companion to api-preflight.py. Runs AFTER every Read / WebFetch / Bash
tool call. If the call constitutes "reading the docs" for a Zoho
endpoint, records the fact to /tmp/claude-skills-read.txt so subsequent
preflight checks let the agent through.

Recognized read patterns:
  - Read tool on ~/.claude/commands/<skill>.md      → skill:<skill>
  - Read tool on .../agent-skills/<skill>/SKILL.md  → skill:<skill>
  - Bash: cat/less/head/tail/bat on either path     → skill:<skill>
  - Bash: curl to /api/skills/<skill>               → skill:<skill>
  - WebFetch to a Zoho docs URL                     → docs:<domain>
  - Bash: curl to a Zoho docs URL                   → docs:<domain>

Never blocks (always exits 0). Silent on non-matching calls.
"""

import json
import os
import re
import sys

STATE_FILE = "/tmp/claude-skills-read.txt"


# Domains that qualify as "Zoho vendor docs" (documentation, not API)
DOC_DOMAIN_RE = re.compile(
    r"(?:developer|help|www)\.zoho\.com|zoho\.com/[a-z]+/developer/docs|"
    r"zoho\.com/[a-z]+/help",
    re.IGNORECASE,
)


def _append_state(entry: str) -> None:
    """Add entry to state file if not already present. Best-effort."""
    try:
        prior = set()
        if os.path.exists(STATE_FILE):
            prior = set(line.strip() for line in open(STATE_FILE) if line.strip())
        if entry in prior:
            return
        prior.add(entry)
        with open(STATE_FILE, "w") as f:
            f.write("\n".join(sorted(prior)) + "\n")
    except Exception:
        pass


def _match_skill_path(path: str) -> "str | None":
    """Return skill name if path is a skill file, else None."""
    if not path:
        return None
    m = re.match(r".*/\.claude/commands/([\w-]+)\.md$", path)
    if m:
        return m.group(1)
    m = re.match(r".*/agent-skills/([\w-]+)/SKILL\.md$", path)
    if m:
        return m.group(1)
    return None


def _extract_skill_from_bash(command: str) -> "str | None":
    """Return skill name if the Bash command reads a skill file."""
    # cat / less / head / tail / bat / more on a skill file
    m = re.search(
        r"(?:cat|less|more|head|tail|bat)\s+[^;&|]*?"
        r"(?:\.claude/commands/|/agent-skills/)([\w-]+?)(?:\.md|/SKILL\.md)\b",
        command,
    )
    if m:
        return m.group(1)
    # curl to /api/skills/<name>
    m = re.search(r"/api/skills/([\w-]+)\b", command)
    if m:
        return m.group(1)
    return None


def _extract_docs_domain(url: str) -> "str | None":
    """Return the domain (host) if url is a Zoho docs URL, else None."""
    if not url:
        return None
    if not DOC_DOMAIN_RE.search(url):
        return None
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else None


def _extract_docs_domain_from_bash(command: str) -> "str | None":
    """Return domain if the Bash command curls a Zoho docs URL."""
    for m in re.finditer(r"https?://[^\s'\"`)|;&]+", command):
        d = _extract_docs_domain(m.group(0))
        if d:
            return d
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}

    if tool == "Read":
        skill = _match_skill_path(inp.get("file_path") or "")
        if skill:
            _append_state(f"skill:{skill}")

    elif tool == "WebFetch":
        d = _extract_docs_domain(inp.get("url") or "")
        if d:
            _append_state(f"docs:{d}")

    elif tool == "Bash":
        cmd = inp.get("command") or ""
        # Skill read via bash
        skill = _extract_skill_from_bash(cmd)
        if skill:
            _append_state(f"skill:{skill}")
        # Docs fetched via bash curl
        d = _extract_docs_domain_from_bash(cmd)
        if d:
            _append_state(f"docs:{d}")

    sys.exit(0)


if __name__ == "__main__":
    main()
