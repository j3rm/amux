#!/bin/bash
# Deploy api-preflight + api-postflight hooks into every org that touches Zoho.
#
# Copies the two hook scripts from /mnt/gitdata/amux/scripts/hooks/ into each
# target org's home/scripts/hooks/ directory (which maps to /home/amux/scripts/
# hooks/ inside the container), and merges the hook config into that org's
# .claude/settings.json without clobbering any existing keys.
#
# Idempotent — safe to re-run.
#
# 2026-08-16 (Jeremy): agents kept guessing at Zoho API shapes when the docs
# were available. This hook blocks Bash calls to Zoho domains unless the
# session has either read the matching skill or WebFetched vendor docs first.

set -euo pipefail

SRC=/mnt/gitdata/amux/scripts/hooks
ORGS_ROOT=/home/jwesley/.amux/orgs

# Orgs that use Zoho (all CD-* client orgs, Cypra-PAA curator, RTG for
# Act!→Zoho migration). Auto-detect CD-* so new client orgs added later
# get hooks without editing this script.
#
# NOT deployed to: EmberCRM, iSchedule, ShareScore, Scorpio (they're
# already Zoho-denied via ~/.amux/orgs/<org>/skills-deny.txt).
TARGET_ORGS=(Cypra RTG)
for _cd_home in "$ORGS_ROOT"/CD-*/home; do
  [ -d "$_cd_home" ] || continue
  _cd_org=$(basename "$(dirname "$_cd_home")")
  TARGET_ORGS+=("$_cd_org")
done

deployed=()
skipped=()

for org in "${TARGET_ORGS[@]}"; do
  home="$ORGS_ROOT/$org/home"
  if [ ! -d "$home" ]; then
    skipped+=("$org(no home)")
    continue
  fi
  # 1) copy scripts (executable)
  mkdir -p "$home/scripts/hooks"
  cp "$SRC/api-preflight.py"  "$home/scripts/hooks/"
  cp "$SRC/api-postflight.py" "$home/scripts/hooks/"
  chmod +x "$home/scripts/hooks/api-preflight.py" "$home/scripts/hooks/api-postflight.py"

  # 2) merge hooks into settings.json
  mkdir -p "$home/.claude"
  settings="$home/.claude/settings.json"
  if [ ! -f "$settings" ]; then
    echo '{}' > "$settings"
  fi
  python3 - "$settings" <<'PYEOF'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception:
    d = {}
if not isinstance(d, dict):
    d = {}
hooks = d.setdefault("hooks", {})

def upsert(event, matcher, cmd):
    lst = hooks.setdefault(event, [])
    # Replace any existing entry with the same matcher targeting the same cmd path
    for entry in lst:
        if entry.get("matcher") == matcher:
            hks = entry.get("hooks", [])
            for h in hks:
                if isinstance(h, dict) and h.get("command", "").endswith(cmd.rsplit("/", 1)[-1]):
                    h["command"] = cmd
                    return
            hks.append({"type": "command", "command": cmd})
            return
    lst.append({"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]})

upsert("PreToolUse",  "Bash",             "/home/amux/scripts/hooks/api-preflight.py")
upsert("PostToolUse", "Bash|Read|WebFetch", "/home/amux/scripts/hooks/api-postflight.py")

open(p, "w").write(json.dumps(d, indent=2))
PYEOF
  deployed+=("$org")
done

echo ""
echo "Deployed to ${#deployed[@]} orgs:"
printf "  %s\n" "${deployed[@]}"
if [ "${#skipped[@]}" -gt 0 ]; then
  echo ""
  echo "Skipped:"
  printf "  %s\n" "${skipped[@]}"
fi
