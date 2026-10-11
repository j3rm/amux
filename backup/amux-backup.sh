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

# ── Step 4b: Project memory files (~/.claude/projects/*/memory) ──────────────
#
# These are the per-project memory notes agents build up over time
# (MEMORY.md indexes + reference_*.md / rule_*.md topic files). Small
# (~5MB total across all projects) and change rarely, but they hold
# hard-won rules that would be painful to lose. The large per-session
# .jsonl transcripts under ~/.claude/projects/*/ are deliberately NOT
# included — only the `memory/` subdirs.

if [ -d "${HOME}/.claude/projects" ]; then
  mkdir -p "${BACKUP_DIR}/memory"
  # rsync every project's memory/ subdir, preserving the project dir
  # name (e.g. -mnt-gitdata-amux) so restore knows where each file
  # belongs. --delete keeps the backup in sync with removals.
  rsync -a --delete \
    --include='*/' \
    --include='*/memory/***' \
    --exclude='*' \
    "${HOME}/.claude/projects/" "${BACKUP_DIR}/memory/"
  MEM_COUNT=$(find "${BACKUP_DIR}/memory" -type f -name '*.md' 2>/dev/null | wc -l)
  echo "${LOG_PREFIX} Backed up ${MEM_COUNT} project memory files"
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

# ── Step 5b: Jeremy host-side global CLAUDE.md ────────────────────────────────
# Small file, high-signal (Jeremy's rules for his own sessions across all
# projects). Recreating from memory is painful — cheap to snapshot.
if [ -f "${HOME}/.claude/CLAUDE.md" ]; then
  mkdir -p "${BACKUP_DIR}/config"
  cp "${HOME}/.claude/CLAUDE.md" "${BACKUP_DIR}/config/host-CLAUDE.md"
fi

# ── Step 5c: Org container specs + per-org secrets ────────────────────────────
#
# ~/.amux/orgs/<Org>.yml         — container spec (mounts, sessions, image)
# ~/.amux/orgs/<Org>/secrets/    — SSH keys (GitHub, codegraph), gitconfig
#
# Without these, restore-verify sees the sessions but ensure_org_container
# can't rebuild any container, and even if it could, containers would boot
# with no ability to push/pull/reach codegraph. THIS is the biggest DR gap
# in earlier versions of this script (Jeremy 2026-09-11 audit).
#
# secrets/ contains PRIVATE keys — backup repo MUST be private on GitHub.
# The rsync mirrors only the specs and secrets, not the multi-GB
# per-container HOMEs (those get rebuilt on first login).

if [ -d "${AMUX_DIR}/orgs" ]; then
  mkdir -p "${BACKUP_DIR}/orgs"
  # Top-level *.yml org specs
  rsync -a --delete \
    --include='*.yml' \
    --exclude='*' \
    "${AMUX_DIR}/orgs/" "${BACKUP_DIR}/orgs/"
  # Per-org secrets/ subdirs (SSH + gitconfig, not the multi-GB home/)
  for org_dir in "${AMUX_DIR}/orgs"/*/; do
    [ -d "${org_dir}secrets" ] || continue
    org_name=$(basename "${org_dir}")
    mkdir -p "${BACKUP_DIR}/orgs/${org_name}"
    rsync -a --delete "${org_dir}secrets/" "${BACKUP_DIR}/orgs/${org_name}/secrets/"
  done
  ORG_SPEC_COUNT=$(ls "${AMUX_DIR}/orgs"/*.yml 2>/dev/null | wc -l)
  ORG_SECRET_COUNT=$(find "${BACKUP_DIR}/orgs" -type d -name 'ssh' 2>/dev/null | wc -l)
  echo "${LOG_PREFIX} Backed up ${ORG_SPEC_COUNT} org specs + ${ORG_SECRET_COUNT} secrets dirs"
fi

# ── Step 5d: Agent-to-agent channels + shared credentials ─────────────────────
#
# ~/.amux/channels/       — JSONL per pair. Small, recoverable from context
#                           but silently lost without backup — save it.
# ~/.amux/shared-creds/   — Jeremy-personal Gmail OAuth for Personal-org
#                           agents. Bind-mounted; needed on first wake.

if [ -d "${AMUX_DIR}/channels" ]; then
  mkdir -p "${BACKUP_DIR}/channels"
  rsync -a --delete "${AMUX_DIR}/channels/" "${BACKUP_DIR}/channels/"
  CHAN_COUNT=$(ls "${AMUX_DIR}/channels/" 2>/dev/null | wc -l)
  echo "${LOG_PREFIX} Backed up ${CHAN_COUNT} channel history files"
fi

if [ -d "${AMUX_DIR}/shared-creds" ]; then
  mkdir -p "${BACKUP_DIR}/config/shared-creds"
  rsync -a --delete "${AMUX_DIR}/shared-creds/" "${BACKUP_DIR}/config/shared-creds/"
fi

# ── Step 5e: Codex config.toml per-org (non-regenerable agent persona config) ─
#
# ~/.amux/orgs/<Org>/home/ is excluded wholesale as "regenerable cache",
# but a session's codex config.toml holds model + reasoning_effort set
# by the operator and is NOT regenerable (restore would land every
# codex session back on the Codex-default model). Snapshot just the
# config.toml file for each org.

if [ -d "${AMUX_DIR}/orgs" ]; then
  mkdir -p "${BACKUP_DIR}/orgs-home-codex"
  CODEX_CFG_COUNT=0
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    org=$(basename "$(dirname "$(dirname "$(dirname "$f")")")")
    mkdir -p "${BACKUP_DIR}/orgs-home-codex/${org}"
    cp "$f" "${BACKUP_DIR}/orgs-home-codex/${org}/config.toml"
    CODEX_CFG_COUNT=$((CODEX_CFG_COUNT + 1))
  done < <(find "${AMUX_DIR}/orgs" -maxdepth 4 -path '*/home/.codex/config.toml' 2>/dev/null)
  echo "${LOG_PREFIX} Backed up ${CODEX_CFG_COUNT} codex config.toml files"
fi

# ── Step 5f: CD agent rulebooks (CLAUDE.md + CD-Audit-Codex AGENTS.md) ───────
#
# These live outside ~/.amux (in /mnt/gitdata/ClientData). About half the
# CD-* client dirs are themselves git repos (NWDDI/* on GitHub), but the
# other half are not, so a CLAUDE.md edit in a non-git dir is unprotected
# without this snapshot. The shared CD-Audit-Codex AGENTS.md at
# /mnt/gitdata/ClientData/_shared/CD-Audit-Codex is also not in any git
# repo and would be lost on restore without this.

mkdir -p "${BACKUP_DIR}/cd-agent-rulebooks"
CD_CLAUDE_COUNT=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  rel=${f#/mnt/gitdata/ClientData/}
  mkdir -p "${BACKUP_DIR}/cd-agent-rulebooks/$(dirname "$rel")"
  cp "$f" "${BACKUP_DIR}/cd-agent-rulebooks/$rel"
  CD_CLAUDE_COUNT=$((CD_CLAUDE_COUNT + 1))
done < <(
  find /mnt/gitdata/ClientData \
    -maxdepth 4 -name 'CLAUDE.md' -not -path '*/.git/*' 2>/dev/null
)
if [ -d /mnt/gitdata/ClientData/_shared/CD-Audit-Codex ]; then
  mkdir -p "${BACKUP_DIR}/cd-agent-rulebooks/_shared/CD-Audit-Codex"
  rsync -a --delete \
    --exclude='audit-reports/' \
    /mnt/gitdata/ClientData/_shared/CD-Audit-Codex/ \
    "${BACKUP_DIR}/cd-agent-rulebooks/_shared/CD-Audit-Codex/"
fi
echo "${LOG_PREFIX} Snapshotted ${CD_CLAUDE_COUNT} CD CLAUDE.md files + CD-Audit-Codex AGENTS.md"

# ── Step 6: System service files ─────────────────────────────────────────────

mkdir -p "${BACKUP_DIR}/system"
for svc in /etc/systemd/system/amux*.service; do
  [ -f "${svc}" ] && cp "${svc}" "${BACKUP_DIR}/system/"
done
[ -f "${HOME}/start-projects.sh" ] && cp "${HOME}/start-projects.sh" "${BACKUP_DIR}/system/"

# ── Step 7: Generate README.md (shown on GitHub repo home page) ───────────────

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
SESSION_LIST=$(ls "${SESSIONS_DIR}"/*.env 2>/dev/null | while read f; do
  name=$(basename "$f" .env)
  dir=$(grep '^CC_DIR=' "$f" 2>/dev/null | sed 's/CC_DIR="//;s/"//' || echo "")
  flags=$(grep '^CC_FLAGS=' "$f" 2>/dev/null | sed 's/CC_FLAGS="//;s/"//' || echo "")
  echo "  - **${name}** — \`${dir}\` ${flags:+| flags: \`${flags}\`}"
done)

cat > "${BACKUP_DIR}/README.md" << RESTORE_EOF
# AMUX System Restore Guide

**Backup timestamp:** ${TIMESTAMP}
**Session count:** ${SESSION_COUNT}

This file is the authoritative guide for restoring AMUX on a new VM. Read it
completely before starting. The backup repo contains everything needed.

**Jeremy-facing quick recovery notes live in Notion.** Cypra owns that
document. If you're Jeremy and this VM is gone: open the Notion page
titled "AMUX — Server Loss Recovery Playbook" for the human-side
sequence (order of ops, who to contact, credential locations). This
README is the machine-side deep detail; the Notion page is the "what
Jeremy actually does" version.

**Any time this backup script or the restore playbook changes, Cypra
must be asked to update the Notion doc** — see the "Doc-sync
reminders" note at the end of this file.

---

## What this backup contains

| Directory | Contents |
|---|---|
| \`sessions/\` | All agent .env configs + .meta.json (conversation UUIDs) |
| \`database/amux.sql\` | Board items, schedules, threads/messages, channels metadata, all tables (SQLite dump) |
| \`database/board.json\` | Board items in JSON for quick review |
| \`database/schedules.json\` | All scheduled tasks |
| \`notes/\` | Agent shared notes |
| \`memory/\` | Per-project MEMORY.md indexes + rule/feedback topic files |
| \`channels/\` | Agent-to-agent channel history (JSONL per pair) |
| \`orgs/*.yml\` | Container specs (mounts, sessions, image) for every org |
| \`orgs/<Org>/secrets/\` | Per-org SSH keys (GitHub, codegraph) + gitconfig |
| \`config/server.env\` | Anthropic API key, Pushover, AMUX_URL — **keep private** |
| \`config/auth_token\` | Dashboard auth token |
| \`config/tls/\` | TLS certificate and private key |
| \`config/shared-creds/\` | Jeremy-personal Gmail OAuth (Personal-org agents) |
| \`config/host-CLAUDE.md\` | Jeremy's host-side global rules for his own sessions |
| \`system/\` | Systemd service files + startup script |

## What this backup does NOT contain

Deliberate exclusions (large, regenerable, or per-run):

- \`~/.claude/projects/*.jsonl\` — conversation history (~1GB, changes constantly). Agents start fresh sessions after restore.
- \`~/.amux/orgs/*/home/\` — per-container Claude Code cache, npm cache, dotfiles (~16GB). Each container re-\`/login\`s on first wake.
- \`~/.amux/logs/\` — server + session logs (~250MB, rotate anyway).
- \`~/.amux/uploads/\` — Pushover screenshots + thread attachments. Referenced by @-mentions but not load-bearing.
- \`~/.amux/skills/\` — synced to \`git@github.com:j3rm/agent-skills\` separately by SCHED-219; restore fetches from there.
- \`/mnt/gitdata/*/*\` — every repo lives on its own GitHub. Restore step 6 clones each org's repos back.

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
mkdir -p ~/.amux/{sessions,notes,tls,orgs,channels,shared-creds}
mkdir -p ~/.claude

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

# Notes + memory
rsync -a notes/  ~/.amux/notes/
rsync -a memory/ ~/.claude/projects/  # per-project MEMORY.md indexes

# Channels (agent-to-agent history)
rsync -a channels/ ~/.amux/channels/

# Jeremy-personal Gmail OAuth
[ -d config/shared-creds ] && rsync -a config/shared-creds/ ~/.amux/shared-creds/

# Jeremy's host global CLAUDE.md
[ -f config/host-CLAUDE.md ] && cp config/host-CLAUDE.md ~/.claude/CLAUDE.md

# Org specs + per-org secrets (CRITICAL: without secrets, no container
# can push/pull to GitHub or reach codegraph)
rsync -a orgs/*.yml ~/.amux/orgs/ 2>/dev/null || true
for org_dir in orgs/*/; do
  [ -d "\${org_dir}secrets" ] || continue
  org_name=\$(basename "\${org_dir}")
  mkdir -p ~/.amux/orgs/\${org_name}/secrets
  rsync -a "\${org_dir}secrets/" ~/.amux/orgs/\${org_name}/secrets/
done

# Perms — MUST be tight or SSH refuses to use the keys
chmod 600 ~/.amux/server.env ~/.amux/auth_token ~/.amux/tls/key.pem
find ~/.amux/orgs -name 'ssh' -type d -exec chmod 700 {} \\;
find ~/.amux/orgs -path '*/ssh/*' -type f ! -name '*.pub' -exec chmod 600 {} \\;
find ~/.amux/orgs -path '*/ssh/*.pub' -type f -exec chmod 644 {} \\;
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

## After restore — verify with restore-verify.sh

The amux repo ships a machine-readable verifier at
\`/mnt/gitdata/amux/backup/restore-verify.sh\`. Run it after step 7 to
get a punch list of what's missing before waking any sessions:

\`\`\`bash
bash /mnt/gitdata/amux/backup/restore-verify.sh
\`\`\`

It checks: DB tables populated, session env-files present, per-org
SSH keys have correct perms + can reach GitHub, TLS cert not expired,
org container specs match session list, server.env has all required
vars. Non-zero exit + coloured punch list = fix before proceeding.

## After restore — tell the restore agent

Once AMUX is up and you have a Claude session running, send it this:

> "You are being restored from backup. Read README.md in the amux-backup
> repo. Run \`bash /mnt/gitdata/amux/backup/restore-verify.sh\` and
> resolve every item it flags. Then verify all sessions are configured
> correctly, check the board for pending items, and audit which agent
> repos are missing or have unpushed work."

---

## Doc-sync reminders — READ IF ANYTHING BELOW CHANGES

The Jeremy-facing recovery playbook lives in **Notion** (Cypra owns
that document). It's the "what Jeremy does" version — human-side
sequence, order of ops, credential locations, who to contact. The
machine-side deep detail is above; the Notion page is the entry point.

**Any change to these needs a Notion update ping to Cypra:**

- What this backup includes / excludes (\`## What this backup contains\`
  and \`## What this backup does NOT contain\` sections above).
- Restore steps 1-8.
- The Prerequisites section (Ubuntu version, packages, npm globals).
- Systemd unit names or paths.
- The known-gaps list (missing repo remotes, unpushed work).
- Off-site backup destinations.

The wiki page at \`/mnt/gitdata/amux/wiki/Server-Loss-Recovery.md\`
holds the reference to the Notion page and a change-log of when
substantive updates were pushed to Cypra. Agents editing this backup
script or the restore playbook should update that wiki entry AND file
a board item to Cypra requesting the Notion update. Do not assume the
Notion page updates itself.

RESTORE_EOF

echo "${LOG_PREFIX} README.md generated"

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
