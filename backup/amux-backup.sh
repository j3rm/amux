#!/bin/bash
# amux-backup.sh — Full AMUX system backup
#
# Backs up all state needed to fully restore AMUX on a new VM:
#   - Session configs (.env + .meta.json for all agents)
#   - SQLite database (board, schedules, notes, history) as SQL dump
#   - Agent notes
#   - Server credentials and TLS cert
#   - Systemd service files and startup scripts
#
# Destination: a private git repo. Set AMUX_BACKUP_REPO in ~/.amux/server.env
# or export it before running. Example:
#   AMUX_BACKUP_REPO=git@github.com:yourorg/amux-backup-private.git
#
# Called by AMUX scheduler (see schedule: amux-backup) or run manually:
#   bash /mnt/gitdata/amux/backup/amux-backup.sh

set -euo pipefail

BACKUP_DIR="${HOME}/.amux-backup"
AMUX_DIR="${HOME}/.amux"
SESSIONS_DIR="${AMUX_DIR}/sessions"
LOG_PREFIX="[amux-backup]"

# Load server.env so AMUX_BACKUP_REPO and AMUX_URL are available
if [ -f "${HOME}/.amux/server.env" ]; then
  set -a; source "${HOME}/.amux/server.env"; set +a
fi

AMUX_BACKUP_REPO="${AMUX_BACKUP_REPO:-}"

echo "${LOG_PREFIX} Starting backup — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# ── Step 1: Init or update the backup git repo ───────────────────────────────

if [ ! -d "${BACKUP_DIR}/.git" ]; then
  echo "${LOG_PREFIX} Initializing backup repo at ${BACKUP_DIR}"
  mkdir -p "${BACKUP_DIR}"
  git -C "${BACKUP_DIR}" init -q
  if [ -n "${AMUX_BACKUP_REPO}" ]; then
    git -C "${BACKUP_DIR}" remote add origin "${AMUX_BACKUP_REPO}"
    git -C "${BACKUP_DIR}" fetch --quiet 2>/dev/null || true
    git -C "${BACKUP_DIR}" checkout main 2>/dev/null || true
  fi
else
  if [ -n "${AMUX_BACKUP_REPO}" ]; then
    git -C "${BACKUP_DIR}" fetch --quiet 2>/dev/null || true
  fi
fi

# ── Step 2: Copy session configs ─────────────────────────────────────────────

mkdir -p "${BACKUP_DIR}/sessions"
rsync -a --delete \
  --include='*.env' \
  --include='*.meta.json' \
  --exclude='*' \
  "${SESSIONS_DIR}/" "${BACKUP_DIR}/sessions/"

SESSION_COUNT=$(ls "${SESSIONS_DIR}"/*.env 2>/dev/null | wc -l)
echo "${LOG_PREFIX} Backed up ${SESSION_COUNT} session configs"

# ── Step 3: SQLite dump (git-friendly text) ───────────────────────────────────

mkdir -p "${BACKUP_DIR}/database"
if [ -f "${AMUX_DIR}/amux.db" ]; then
  sqlite3 "${AMUX_DIR}/amux.db" .dump > "${BACKUP_DIR}/database/amux.sql"
  # Also export key tables as JSON for quick inspection
  sqlite3 "${AMUX_DIR}/amux.db" -json \
    "SELECT id,title,desc,status,session,creator,due FROM issues WHERE deleted IS NULL ORDER BY created" \
    > "${BACKUP_DIR}/database/board.json" 2>/dev/null || true
  sqlite3 "${AMUX_DIR}/amux.db" -json \
    "SELECT id,title,kind,cron,session,enabled FROM schedules ORDER BY id" \
    > "${BACKUP_DIR}/database/schedules.json" 2>/dev/null || true
  echo "${LOG_PREFIX} SQLite dumped"
fi

# ── Step 4: Agent notes ───────────────────────────────────────────────────────

if [ -d "${AMUX_DIR}/notes" ]; then
  mkdir -p "${BACKUP_DIR}/notes"
  rsync -a --delete "${AMUX_DIR}/notes/" "${BACKUP_DIR}/notes/"
  NOTE_COUNT=$(ls "${AMUX_DIR}/notes/" 2>/dev/null | wc -l)
  echo "${LOG_PREFIX} Backed up ${NOTE_COUNT} notes"
fi

# ── Step 5: Server config (credentials) ──────────────────────────────────────

mkdir -p "${BACKUP_DIR}/config"
for f in server.env defaults.env auth_token; do
  [ -f "${AMUX_DIR}/${f}" ] && cp "${AMUX_DIR}/${f}" "${BACKUP_DIR}/config/${f}"
done

# TLS cert and key
if [ -d "${AMUX_DIR}/tls" ]; then
  mkdir -p "${BACKUP_DIR}/config/tls"
  rsync -a "${AMUX_DIR}/tls/" "${BACKUP_DIR}/config/tls/"
fi

# ── Step 6: System service files ─────────────────────────────────────────────

mkdir -p "${BACKUP_DIR}/system"
for svc in /etc/systemd/system/amux*.service; do
  [ -f "${svc}" ] && cp "${svc}" "${BACKUP_DIR}/system/"
done
[ -f "${HOME}/start-projects.sh" ] && cp "${HOME}/start-projects.sh" "${BACKUP_DIR}/system/"

# ── Step 7: Generate RESTORE.md ───────────────────────────────────────────────

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
SESSION_LIST=$(ls "${SESSIONS_DIR}"/*.env 2>/dev/null | while read f; do
  name=$(basename "$f" .env)
  dir=$(grep '^CC_DIR=' "$f" 2>/dev/null | sed 's/CC_DIR="//;s/"//' || echo "")
  flags=$(grep '^CC_FLAGS=' "$f" 2>/dev/null | sed 's/CC_FLAGS="//;s/"//' || echo "")
  echo "  - **${name}** — \`${dir}\` ${flags:+| flags: \`${flags}\`}"
done)

cat > "${BACKUP_DIR}/RESTORE.md" << RESTORE_EOF
# AMUX System Restore Guide

**Backup timestamp:** ${TIMESTAMP}
**Session count:** ${SESSION_COUNT}

This file is the authoritative guide for restoring AMUX on a new VM. Read it
completely before starting. The backup repo contains everything needed.

---

## What this backup contains

| Directory | Contents |
|---|---|
| \`sessions/\` | All agent .env configs + .meta.json (conversation UUIDs) |
| \`database/amux.sql\` | Board items, schedules, notes, history (SQLite dump) |
| \`database/board.json\` | Board items in JSON for quick review |
| \`database/schedules.json\` | All scheduled tasks |
| \`notes/\` | Agent shared notes |
| \`config/server.env\` | Anthropic API key, Pushover, AMUX_URL — **keep private** |
| \`config/auth_token\` | Dashboard auth token |
| \`config/tls/\` | TLS certificate and private key |
| \`system/\` | Systemd service files + startup script |

---

## Prerequisites on the new VM

\`\`\`bash
# Ubuntu 22.04+
sudo apt update && sudo apt install -y python3 python3-pip tmux git sqlite3 rsync curl
pip3 install schedule requests

# Claude Code CLI
npm install -g @anthropic-ai/claude-code

# SSH key for GitHub access (generate or restore from secure vault)
ssh-keygen -t ed25519 -C "amux@newvm"
# Add the public key to GitHub → Settings → SSH keys
\`\`\`

---

## Restore steps

### 1. Clone this backup repo

\`\`\`bash
git clone <this-repo-url> ~/amux-backup-restore
cd ~/amux-backup-restore
\`\`\`

### 2. Restore ~/.amux structure

\`\`\`bash
mkdir -p ~/.amux/sessions ~/.amux/notes ~/.amux/tls

# Session configs (all agents)
cp sessions/*.env    ~/.amux/sessions/
cp sessions/*.meta.json ~/.amux/sessions/ 2>/dev/null || true

# Server credentials
cp config/server.env  ~/.amux/server.env
cp config/auth_token  ~/.amux/auth_token
cp config/defaults.env ~/.amux/defaults.env 2>/dev/null || true

# TLS
cp config/tls/cert.pem ~/.amux/tls/
cp config/tls/key.pem  ~/.amux/tls/

# Notes
rsync -a notes/ ~/.amux/notes/

chmod 600 ~/.amux/server.env ~/.amux/auth_token ~/.amux/tls/key.pem
\`\`\`

### 3. Restore the database

\`\`\`bash
# Import the SQL dump — restores board, schedules, history
sqlite3 ~/.amux/amux.db < database/amux.sql
echo "Database restored — $(sqlite3 ~/.amux/amux.db 'SELECT COUNT(*) FROM issues') board items"
\`\`\`

### 4. Clone the AMUX server

\`\`\`bash
mkdir -p /mnt/gitdata
cd /mnt/gitdata
git clone git@github.com:mixpeek/amux.git amux
\`\`\`

### 5. Install systemd services

\`\`\`bash
sudo cp system/amux.service        /etc/systemd/system/
sudo cp system/amux-serve.service  /etc/systemd/system/
sudo cp system/amux-projects.service /etc/systemd/system/
cp system/start-projects.sh ~/start-projects.sh
chmod +x ~/start-projects.sh

sudo systemctl daemon-reload
sudo systemctl enable amux amux-serve amux-projects
sudo systemctl start amux
\`\`\`

### 6. Clone all agent repos

Each session below needs its working directory to exist. The session's .env
specifies CC_DIR. Clone the corresponding repo into that path.

**Sessions as of ${TIMESTAMP}:**

${SESSION_LIST}

For repos without a remote (see audit section below), you need a copy from
backup or the original disk.

### 7. Verify AMUX is up

\`\`\`bash
# Load server config
source ~/.amux/server.env

# Check API
curl -sk \$AMUX_URL/api/sessions | python3 -c "
import json,sys
ss = json.load(sys.stdin)
print(f'Sessions: {len(ss)}')
"

# Dashboard should be at \$AMUX_URL
\`\`\`

### 8. Start sessions

\`\`\`bash
# Sessions that auto-start on boot are in ~/start-projects.sh
# To start others manually:
amux start <session-name>
\`\`\`

---

## Conversation history (optional but valuable)

Claude Code conversation histories live in \`~/.claude/projects/\` (1GB total).
These are NOT in this backup by default — they're large and change constantly.

If you have a separate \`~/.claude\` backup:
\`\`\`bash
rsync -a /path/to/claude-backup/ ~/.claude/
\`\`\`

Without this, agents start fresh sessions. Their conversation UUIDs in
\`sessions/*.meta.json\` will no longer match, but AMUX handles this gracefully
by starting a new named conversation.

---

## Known gaps (repos without remotes — code only on original disk)

At backup time these had no GitHub remote and require manual recovery:
- \`EmberCRM/Ember_Auth_API_Core\`
- \`EmberCRM/Ember_CRM_API_Core\`
- \`EmberCRM/Ember_Core_Documents\`
- \`ShareScore/ShareScore_HF_Dashboard\`
- \`ShareScore/Documentation\`

And these had significant unpushed commits:
- \`Ember_CRM_iOS\` — 68+ commits ahead
- \`Ember_CRM_Flutter\` — 41+ commits ahead
- \`Ember_OPS_Web_AngularJS\` — 5+ commits ahead

---

## After restore — tell the restore agent

Once AMUX is up and you have a Claude session running, send it this:

> "You are being restored from backup. Read RESTORE.md in the amux-backup repo.
> Verify all sessions are configured correctly, check the board for pending items,
> and audit which agent repos are missing or have unpushed work."

RESTORE_EOF

echo "${LOG_PREFIX} RESTORE.md generated"

# ── Step 8: Commit and push ───────────────────────────────────────────────────

cd "${BACKUP_DIR}"
git add -A

if git diff --cached --quiet; then
  echo "${LOG_PREFIX} Nothing changed since last backup"
else
  git -c user.name="amux-backup" -c user.email="amux@localhost" \
    commit -q -m "backup: ${TIMESTAMP} | ${SESSION_COUNT} sessions"
  echo "${LOG_PREFIX} Committed"

  if [ -n "${AMUX_BACKUP_REPO}" ] && git remote get-url origin &>/dev/null; then
    git push -q origin main 2>/dev/null || git push -q origin master 2>/dev/null || \
      git push -q -u origin "$(git branch --show-current)" 2>/dev/null || \
      echo "${LOG_PREFIX} WARNING: push failed — check AMUX_BACKUP_REPO and SSH key"
    echo "${LOG_PREFIX} Pushed to ${AMUX_BACKUP_REPO}"
  else
    echo "${LOG_PREFIX} No remote configured — backup is local only at ${BACKUP_DIR}"
    echo "${LOG_PREFIX} Set AMUX_BACKUP_REPO in ~/.amux/server.env to enable push"
  fi
fi

echo "${LOG_PREFIX} Done — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
