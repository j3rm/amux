#!/bin/bash
# Nightly disk hygiene for the amux host.
# Invoked by an amux schedule (kind=shell). Runs as the amux-server process
# user (jwesley), so no sudo — only user-space caches are touched.
# Pushover creds are inherited from ~/.amux/server.env (AMUX_PUSHOVER_*).

set -uo pipefail

LOG=/tmp/amux-disk-cleanup.log
MOUNT=/
WARN_PRE=88     # alert BEFORE cleanup if we've drifted into the danger zone
WARN_POST=85   # alert AFTER cleanup if we still can't get below this
CRITICAL=94    # emergency (priority 2) if we hit this at any point

ts()   { date '+%Y-%m-%d %H:%M:%S'; }
log()  { echo "[$(ts)] $*" | tee -a "$LOG" >&2; }
pct()  { df --output=pcent "$MOUNT" | tail -1 | tr -dc '0-9'; }
freeG(){ df -BG --output=avail "$MOUNT" | tail -1 | tr -dc '0-9'; }

push() {
  local title="$1" msg="$2" prio="${3:-0}"
  if [ -z "${AMUX_PUSHOVER_TOKEN:-}" ] || [ -z "${AMUX_PUSHOVER_USER:-}" ]; then
    log "pushover: env not set, skipped ($title)"
    return
  fi
  curl -sS --max-time 10 \
    --form-string "token=$AMUX_PUSHOVER_TOKEN" \
    --form-string "user=$AMUX_PUSHOVER_USER" \
    --form-string "title=$title" \
    --form-string "message=$msg" \
    --form-string "priority=$prio" \
    https://api.pushover.net/1/messages.json >/dev/null 2>&1 \
    && log "pushover sent [p$prio]: $title" \
    || log "pushover FAILED to send: $title"
}

log "=== disk-cleanup start ==="
pre_pct=$(pct); pre_free=$(freeG)
log "before: ${pre_pct}% used, ${pre_free}G free"

# Early warning — before we even try to clean, tell Jeremy things drifted
if [ "$pre_pct" -ge "$CRITICAL" ]; then
  push "amux disk CRITICAL" "Root at ${pre_pct}% (${pre_free}G free) — running cleanup, but likely need manual intervention." 2
elif [ "$pre_pct" -ge "$WARN_PRE" ]; then
  push "amux disk warning" "Root at ${pre_pct}% (${pre_free}G free). Running nightly cleanup." 1
fi

# --- User-space, non-sudo cleanups ---

# 1. Crash dumps older than 3d (files are owned jwesley:root, world-writable dir)
find /var/crash -type f -name '*.crash' -mtime +3 -delete 2>/dev/null \
  && log "crash-dumps: pruned >3d"

# 2. Old Claude Code conversation logs (>30 days) — historical only
find /home/jwesley/.claude/projects -type f -name '*.jsonl' -mtime +30 -delete 2>/dev/null \
  && log ".claude/projects: pruned .jsonl >30d"

# 3. npm cache
if command -v npm >/dev/null 2>&1; then
  npm cache clean --force >/dev/null 2>&1 && log "npm cache cleared"
fi

# 4. dotnet nuget cache
if command -v dotnet >/dev/null 2>&1; then
  dotnet nuget locals all --clear >/dev/null 2>&1 && log "dotnet nuget cache cleared"
fi

# 5. pip cache
if command -v pip3 >/dev/null 2>&1; then
  pip3 cache purge >/dev/null 2>&1 && log "pip cache purged"
fi

# 6. User systemd journal (if any) — most journals are system-wide (need sudo);
#    this only affects the per-user journal.
journalctl --user --vacuum-time=7d >/dev/null 2>&1 && log "user journal vacuumed"

# --- Report ---
post_pct=$(pct); post_free=$(freeG)
delta=$((post_free - pre_free))
log "after:  ${post_pct}% used, ${post_free}G free (delta ${delta}G)"

# Post-cleanup alert — cleanup couldn't get us clear
if [ "$post_pct" -ge "$CRITICAL" ]; then
  push "amux disk STILL CRITICAL" "Post-cleanup: ${post_pct}% (${post_free}G free). Was ${pre_pct}%. Manual triage needed — check ~/.amux/orgs container caches." 2
elif [ "$post_pct" -ge "$WARN_POST" ]; then
  push "amux disk still high" "Post-cleanup: ${post_pct}% (${post_free}G free). Was ${pre_pct}%. ~/.amux/orgs is likely the culprit (${pre_free}G→${post_free}G recovered here)." 1
fi

log "=== disk-cleanup done ==="
exit 0
