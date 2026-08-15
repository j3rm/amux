#!/bin/bash
# Nightly skills-sync: amux DB → /mnt/gitdata/agent-skills → GitHub.
# Invoked by amux schedule (kind=shell, cron '7 3 * * *') — runs before
# disk-cleanup so the sync commit isn't racing anything.
#
# Why this exists (2026-08-15):
#   Two skill stores existed and had drifted. Some skills lived only in
#   the amux DB (no GitHub backup); some lived only in the git repo (not
#   deployed to containers). The one-time reconciliation is in commit
#   77a26f3 on j3rm/agent-skills. This script keeps them in sync going
#   forward: agents write to the DB via `amux skills set`; this promotes
#   the DB body into the git repo nightly and pushes to GitHub.
#
# Rules:
#   - DB → git only (agents can't write to the git repo — mount is
#     read-only in containers). If a curator (Cypra-PAA) needs to edit
#     the git repo directly they can, but that direction is not what
#     this script handles; that's SCHED-42's weekly job.
#   - If the git tree already has a newer commit than the DB (curator
#     bumped it manually), the DB-body write overwrites it. Cypra-PAA is
#     the one who should reconcile any real conflict.
#   - Push failures Pushover Jeremy.

set -uo pipefail

REPO=/mnt/gitdata/agent-skills
LOG=/tmp/amux-skills-sync.log

# Load AMUX_PUSHOVER_* from server.env (for alert()). Force AMUX_URL to
# localhost *after* — server.env sets it to the public cloud URL, which
# requires OAuth cookies we don't have here.
if [ -f ~/.amux/server.env ]; then
  set -a; . ~/.amux/server.env; set +a
fi
AMUX_URL="https://localhost:8822"
export AMUX_URL REPO

ts()   { date '+%Y-%m-%d %H:%M:%S'; }
log()  { echo "[$(ts)] $*" | tee -a "$LOG" >&2; }
alert() {
  local msg="$1"
  log "ALERT: $msg"
  if [ -n "${AMUX_PUSHOVER_TOKEN:-}" ] && [ -n "${AMUX_PUSHOVER_USER:-}" ]; then
    curl -sk --max-time 10 https://api.pushover.net/1/messages.json \
      -F token="$AMUX_PUSHOVER_TOKEN" -F user="$AMUX_PUSHOVER_USER" \
      -F title="amux skills-sync FAILED" -F message="$msg" -F priority=1 \
      >/dev/null 2>&1 || true
  fi
}

log "=== skills-sync start ==="

cd "$REPO" || { alert "cannot cd $REPO"; exit 1; }

# Make sure we're clean and up-to-date before writing.
if [ -n "$(git status --porcelain)" ]; then
  alert "$REPO has uncommitted changes before sync — someone is mid-curation. Skipping."
  git status --short | tee -a "$LOG" >&2
  exit 1
fi
git fetch origin master 2>&1 | tee -a "$LOG" >&2
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)
if [ "$LOCAL" != "$REMOTE" ]; then
  # Local is behind or diverged. Try fast-forward; anything else needs a human.
  if ! git merge --ff-only origin/master 2>&1 | tee -a "$LOG" >&2; then
    alert "$REPO diverged from origin/master (local=$LOCAL remote=$REMOTE) — cannot fast-forward. Skipping."
    exit 1
  fi
fi

# Pull every skill from the DB and write to the repo. Capture python's
# exit code (tee would otherwise mask a hard failure).
python3 - 2>&1 <<'PYEOF' | tee -a "$LOG" >&2
import json, os, ssl, sys, urllib.request
ctx = ssl._create_unverified_context()
base = os.environ.get('AMUX_URL', 'https://localhost:8822')
repo = os.environ.get('REPO', '/mnt/gitdata/agent-skills')

try:
    skills = json.loads(urllib.request.urlopen(base + '/api/skills', context=ctx, timeout=15).read())
except Exception as e:
    print(f"FAIL listing skills from {base}: {e}"); sys.exit(2)

for s in skills:
    name = s['name']
    if '/' in name or name.startswith('.') or not name:
        print(f"  SKIP {name!r} (unsafe)"); continue
    try:
        d = json.loads(urllib.request.urlopen(f"{base}/api/skills/{name}", context=ctx, timeout=15).read())
    except Exception as e:
        print(f"  FAIL fetching {name}: {e}"); continue
    body = d.get('content') or ''
    if not body.strip():
        print(f"  SKIP {name} (empty body)"); continue
    d_ = os.path.join(repo, name)
    os.makedirs(d_, exist_ok=True)
    fpath = os.path.join(d_, 'SKILL.md')
    prior = open(fpath).read() if os.path.exists(fpath) else ''
    if prior == body:
        continue
    open(fpath, 'w').write(body)
    print(f"  updated {name} ({len(body)} chars)")
PYEOF
PY_EXIT=${PIPESTATUS[0]}
if [ "$PY_EXIT" -ne 0 ]; then
  alert "python fetch stage failed (exit $PY_EXIT) — see $LOG"
  exit 1
fi

# Commit + push if anything changed.
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  COUNT=$(git diff --cached --stat | tail -1 | awk '{print $1}')
  git -c user.name='amux-skills-sync' -c user.email='amux@j3software.com' \
    commit -m "nightly sync: DB → repo ($COUNT files touched)" 2>&1 | tee -a "$LOG" >&2
  if ! git push origin master 2>&1 | tee -a "$LOG" >&2; then
    alert "git push origin master FAILED — commit is local"
    exit 1
  fi
  log "pushed sync commit ($COUNT files touched)"
else
  log "no changes — DB matches repo"
fi

log "=== skills-sync done ==="
