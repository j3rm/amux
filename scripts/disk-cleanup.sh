#!/bin/bash
# Nightly disk hygiene for the amux host.
# Invoked by an amux schedule (kind=shell, SCHED-49, cron '15 3 * * *').
# Runs as the amux-server process user (jwesley), so no sudo — only
# user-space caches are touched.
# Pushover creds are inherited from ~/.amux/server.env (AMUX_PUSHOVER_*).
#
# HISTORY:
# 2026-07-22: initial version. Cleaned HOST caches only (~/.npm etc.).
# 2026-08-11: 3rd disk-full incident; Jeremy can't add more LV space.
#             Root cause: prior version never touched the per-org
#             container home caches at ~/.amux/orgs/*/home/.npm/_cacache,
#             .pub-cache, .nuget/packages. Those had grown to 23 GB
#             collectively. Rewritten to traverse them explicitly, plus
#             docker image prune for dangling images.

set -uo pipefail

LOG=/tmp/amux-disk-cleanup.log
MOUNT=/
WARN_PRE=88     # alert BEFORE cleanup if we've drifted into the danger zone
WARN_POST=85    # alert AFTER cleanup if we still can't get below this
CRITICAL=94     # emergency (priority 2) if we hit this at any point

ts()   { date '+%Y-%m-%d %H:%M:%S'; }
log()  { echo "[$(ts)] $*" | tee -a "$LOG" >&2; }
pct()  { df --output=pcent "$MOUNT" | tail -1 | tr -dc '0-9'; }
freeG(){ df -BG --output=avail "$MOUNT" | tail -1 | tr -dc '0-9'; }
# Human-readable size of a directory (0 if missing). Used only for logging.
sz()   { du -sh "$1" 2>/dev/null | awk '{print $1}'; }

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

# Delete a per-org path across every org under ~/.amux/orgs/*/home/.
# Logs the pre-delete size per org for visibility. rel is the path
# fragment AFTER 'home/', e.g. '.npm/_cacache'.
prune_per_org() {
  local rel="$1"
  local total_before=0
  local removed=0
  for d in /home/jwesley/.amux/orgs/*/home/"$rel"; do
    [ -e "$d" ] || continue
    local before_kb
    before_kb=$(du -sk "$d" 2>/dev/null | awk '{print $1}')
    total_before=$((total_before + before_kb))
    rm -rf -- "$d" && removed=$((removed + 1))
  done
  if [ "$removed" -gt 0 ]; then
    # convert kB to MB
    local mb=$((total_before / 1024))
    log "per-org: pruned $removed × $rel (~${mb}MB reclaimed)"
  fi
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

# ─── HOST-level caches (jwesley's home directly) ────────────────────────

# 1. Crash dumps older than 3d
find /var/crash -type f -name '*.crash' -mtime +3 -delete 2>/dev/null \
  && log "crash-dumps: pruned >3d"

# 2. Old HOST Claude Code conversation logs (>30 days)
find /home/jwesley/.claude/projects -type f -name '*.jsonl' -mtime +30 -delete 2>/dev/null \
  && log "host .claude/projects: pruned .jsonl >30d"

# 3. Host npm cache (rare — most work happens in org containers)
if command -v npm >/dev/null 2>&1; then
  npm cache clean --force >/dev/null 2>&1 && log "host npm cache cleared"
fi

# 4. Host dotnet nuget cache
if command -v dotnet >/dev/null 2>&1; then
  dotnet nuget locals all --clear >/dev/null 2>&1 && log "host dotnet nuget cache cleared"
fi

# 5. Host pip cache
if command -v pip3 >/dev/null 2>&1; then
  pip3 cache purge >/dev/null 2>&1 && log "host pip cache purged"
fi

# 6. User systemd journal (if any) — system journal needs sudo, not here.
journalctl --user --vacuum-time=7d >/dev/null 2>&1 && log "user journal vacuumed"

# ─── PER-ORG container home caches (the 23 GB blind spot pre-2026-08-11) ─
#
# Every org container bind-mounts its HOME from ~/.amux/orgs/<org>/home/.
# The container writes package caches into standard locations under that
# HOME, which the host sees directly. Nothing else was reaching in here.
#
# All three targets are pure package caches — the tarballs re-download on
# the next install; no config or code is affected.
prune_per_org ".npm/_cacache"       # npm downloaded tarballs (BIGGEST — was 19 GB total 2026-08-11)
prune_per_org ".pub-cache"          # Dart / Flutter package cache
prune_per_org ".nuget/packages"     # NuGet global packages cache
prune_per_org ".cache/pip"          # pip wheel cache
prune_per_org ".cache/yarn"         # yarn v1 cache
prune_per_org ".cache/pnpm"         # pnpm cache

# 7. Per-org old Claude Code JSONLs (>30d)
for d in /home/jwesley/.amux/orgs/*/home/.claude/projects; do
  [ -d "$d" ] || continue
  find "$d" -type f -name '*.jsonl' -mtime +30 -delete 2>/dev/null
done
log "per-org .claude/projects: pruned .jsonl >30d"

# 8. Per-org old codex logs (>30d) if the tree exists
for d in /home/jwesley/.amux/orgs/*/home/.codex; do
  [ -d "$d" ] || continue
  find "$d" -type f \( -name '*.log' -o -name '*.jsonl' \) -mtime +30 -delete 2>/dev/null
done
log "per-org .codex: pruned old logs >30d"

# ─── Docker (safe: only removes UNUSED images/containers/volumes) ───────
if command -v docker >/dev/null 2>&1; then
  # -f = no confirm prompt. Only touches dangling/unreferenced items.
  # Never touches images with a running container attached.
  docker image prune -f >/dev/null 2>&1 && log "docker image prune (dangling)"
  # Aggressive: prune stopped containers too (running ones untouched).
  # amux keeps its org containers RUNNING, so this is safe for us.
  docker container prune -f >/dev/null 2>&1 && log "docker container prune (stopped)"
fi

# ─── Old amux backups (>60d) ────────────────────────────────────────────
find /home/jwesley/.amux/backups -maxdepth 1 -type f \
     \( -name '*-old.jsonl' -o -name '*.jsonl' -o -name '*.bak' \) \
     -mtime +60 -delete 2>/dev/null \
  && log "amux backups: pruned >60d"

# ─── Report ─────────────────────────────────────────────────────────────
post_pct=$(pct); post_free=$(freeG)
delta=$((post_free - pre_free))
log "after:  ${post_pct}% used, ${post_free}G free (delta ${delta}G)"

# Post-cleanup alert — cleanup couldn't get us clear
if [ "$post_pct" -ge "$CRITICAL" ]; then
  push "amux disk STILL CRITICAL" "Post-cleanup: ${post_pct}% (${post_free}G free). Was ${pre_pct}%. Manual triage needed — check ~/.amux/orgs container writable layers (docker ps -s) and per-org home dirs (du -sh ~/.amux/orgs/*/)." 2
elif [ "$post_pct" -ge "$WARN_POST" ]; then
  push "amux disk still high" "Post-cleanup: ${post_pct}% (${post_free}G free). Was ${pre_pct}%. Delta ${delta}G recovered. Docker containers writable layers may be next lever — see docker ps -s." 1
fi

log "=== disk-cleanup done ==="
exit 0
