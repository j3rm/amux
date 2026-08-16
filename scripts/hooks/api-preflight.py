#!/usr/bin/env python3
"""PreToolUse hook — block Zoho API calls unless the agent has read the docs.

Deployed to every container that touches Zoho (CD-*, Cypra, RTG). Runs
before every Bash tool call. Exit 0 = allow. Exit 2 = block (stderr goes
back to the model as feedback).

Trigger (2026-08-16, Jeremy): agents kept guessing at Zoho API endpoint
shapes when perfectly good documentation existed — both our local skills
and Zoho's own developer docs on the web. This hook makes guessing
impossible for the hottest failure surface: any Bash line that calls a
Zoho domain and hasn't been preceded by either a skill read or a
vendor-docs fetch gets blocked with a clear "read this first" message.

The state file is per-container (fresh on container restart) at
/tmp/claude-skills-read.txt — populated by the companion PostToolUse
hook api-postflight.py.
"""

import json
import os
import re
import sys

STATE_FILE = "/tmp/claude-skills-read.txt"


# ── Domain / path → skill map ───────────────────────────────────────────
# Most specific first — first match wins.
#
# For skills we have locally, name the skill. If the URL matches a Zoho
# domain but not a specific skill, we still enforce (fallback bucket
# "zoho-generic") — the block message just says "read A Zoho skill or
# WebFetch the vendor docs".
RULES = [
    # crm.zoho.com paths — client scripts / inventory templates use browser session
    (r"crm\.zoho\.com/[^/]+/settings/client_script",   "zoho-crm-cscript"),
    (r"crm\.zoho\.com/dpdel/",                          "zoho-crm-inventory-templates"),
    (r"crm\.zoho\.com/.*\.do\b",                        "zoho-crm-inventory-templates"),
    (r"crm\.zoho\.com/crm/v2/settings/functions",       "zoho-crm-functions"),
    # zohoapis.com paths — most specific CRM sub-APIs first
    (r"zohoapis\.com/crm/[^/]+/settings/functions",     "zoho-crm-functions"),
    (r"zohoapis\.com/crm/[^/]+/settings/automation/workflow_rules",
                                                        "zoho-crm-workflows"),
    (r"zohoapis\.com/crm/[^/]+/settings/blueprints",    "zoho-crm-blueprint"),
    (r"zohoapis\.com/crm/[^/]+/settings/inventory_templates",
                                                        "zoho-crm-inventory-templates"),
    (r"zohoapis\.com/crm/[^/]+/settings/notifications", "zoho-crm-workflows"),
    (r"zohoapis\.com/crm",                              "zoho-crm"),
    # Other Zoho apps
    (r"dataprep\.zoho\.com|dataprepapi",                "zoho-dataprep"),
    (r"analyticsapi\.zoho\.com",                        "zoho-analytics"),
    (r"zohoapis\.com/books|books\.zoho\.com/api",       "zoho-books"),
    (r"zohoapis\.com/creator|creator\.zoho\.com",       "zoho-creator"),
    (r"catalyst\.zoho\.com|zohoapis\.com/catalyst",     "zoho-catalyst"),
    (r"forms\.zoho\.com|zohoapis\.com/forms",           "zoho-forms"),
    (r"zohoapis\.com/projects|projects\.zoho\.com",     "zoho-projects"),
    (r"accounts\.zoho\.com/oauth",                      "zoho-auth"),
    # Catch-all for any other Zoho endpoint we haven't mapped yet
    (r"(?:^|[^\w.])(?:www\.)?zohoapis\.com",            "zoho-generic"),
    (r"[a-z0-9.-]*\.zoho\.com",                         "zoho-generic"),
]


# Skill files that count as "generic Zoho docs read"
ZOHO_SKILL_NAMES = {
    "zoho-crm", "zoho-crm-functions", "zoho-crm-workflows",
    "zoho-crm-blueprint", "zoho-crm-inventory-templates",
    "zoho-crm-cscript", "zoho-crm-session-refresh",
    "zoho-analytics", "zoho-books", "zoho-creator", "zoho-catalyst",
    "zoho-dataprep", "zoho-forms", "zoho-projects", "zoho-auth",
    "zoho-onboarding",
}


def _read_state():
    """Return the set of entries in the state file. Missing → empty set."""
    try:
        if os.path.exists(STATE_FILE):
            return set(line.strip() for line in open(STATE_FILE) if line.strip())
    except Exception:
        pass
    return set()


def _match_rule(command: str):
    """Return (matched_pattern, matched_skill) or (None, None)."""
    for pattern, skill in RULES:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern, skill
    return None, None


def _block(skill: str, matched_url_fragment: str):
    """Emit the block message and exit 2."""
    msg = [
        f"BLOCKED by api-preflight hook.",
        f"",
        f"You are about to call a Zoho endpoint (URL fragment: {matched_url_fragment!r}) "
        f"but you have not read documentation for it this session.",
        f"",
        f"Two ways to unblock. Do EITHER one (30 seconds):",
        f"",
    ]
    if skill == "zoho-generic":
        msg += [
            f"1. Read ANY Zoho skill that covers this endpoint. List them:",
            f"     ls ~/.claude/commands/ | grep '^zoho-'",
            f"   Then cat the relevant one.",
        ]
    else:
        msg += [
            f"1. Read the matching skill:",
            f"     cat ~/.claude/commands/{skill}.md",
        ]
    msg += [
        f"",
        f"2. OR WebFetch the vendor documentation for this endpoint:",
        f"     Zoho docs live at zoho.com/*/developer/docs, help.zoho.com,",
        f"     and developer.zoho.com. Use the WebFetch tool with the exact",
        f"     doc page URL for the endpoint you're calling.",
        f"",
        f"After doing either, retry your original command.",
        f"",
        f"WHY this hook exists (Jeremy, 2026-08-16): agents keep guessing at",
        f"Zoho API shapes when the docs are right there. Every guess costs a",
        f"debugging cycle. Reading the docs first saves that cycle. If you",
        f"believe this block is a false positive (command shouldn't hit any",
        f"Zoho API), file a board task to amux-helper with the command.",
    ]
    print("\n".join(msg), file=sys.stderr)
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Malformed input → don't block, log to stderr
        print("api-preflight: malformed stdin JSON — allowing", file=sys.stderr)
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = (data.get("tool_input") or {}).get("command") or ""
    if not command:
        sys.exit(0)

    pattern, skill = _match_rule(command)
    if not skill:
        sys.exit(0)  # not a Zoho call — allow

    state = _read_state()

    # Any Zoho skill read this session unblocks generic Zoho calls
    if skill == "zoho-generic":
        for s in state:
            if s.startswith("skill:") and s[6:] in ZOHO_SKILL_NAMES:
                sys.exit(0)
    else:
        if f"skill:{skill}" in state:
            sys.exit(0)

    # Any WebFetch to a Zoho docs domain unblocks
    for s in state:
        if s.startswith("docs:") and "zoho" in s:
            sys.exit(0)

    # Extract the URL-ish fragment from the command for a useful error hint
    m = re.search(r"https?://[^\s'\"`)|;&]+", command)
    frag = m.group(0)[:80] if m else "<no URL found in command>"
    _block(skill, frag)


if __name__ == "__main__":
    main()
