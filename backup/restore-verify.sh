#!/bin/bash
# restore-verify.sh — post-restore sanity check for a fresh AMUX VM.
#
# Reads only. Emits a coloured punch list of anything missing / broken,
# and returns non-zero if ANY check fails so a wrapping script can gate on it.
#
# Usage:
#   bash /mnt/gitdata/amux/backup/restore-verify.sh
#
# Exit code:
#   0 — no FAILURES. Safe to wake sessions. Warnings may still appear
#       above and are advisory — review but non-blocking.
#   1 — at least one FAILURE. Fix before waking sessions.
#
# Cypra-owned Jeremy-facing recovery playbook lives in Notion. See
# wiki/Server-Loss-Recovery.md for the pointer + change log.

AMUX_DIR="${HOME}/.amux"
FAIL=0
WARN=0

# Colours only if stdout is a TTY (systemd/cron logs stay clean).
if [ -t 1 ]; then
  R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[34m'; N=$'\e[0m'
else
  R=""; G=""; Y=""; B=""; N=""
fi

ok()   { echo "${G}✓${N} $*"; }
fail() { echo "${R}✗${N} $*"; FAIL=$((FAIL+1)); }
warn() { echo "${Y}!${N} $*"; WARN=$((WARN+1)); }
head() { echo; echo "${B}── $* ──${N}"; }

head "1. Core paths present"
for p in "${AMUX_DIR}" "${AMUX_DIR}/sessions" "${AMUX_DIR}/tls" \
         "${AMUX_DIR}/orgs" "${HOME}/.claude"; do
  [ -d "$p" ] && ok "$p" || fail "missing directory: $p"
done

head "2. server.env — required vars"
if [ ! -f "${AMUX_DIR}/server.env" ]; then
  fail "server.env not found — restore step 2 not run"
else
  ok "server.env present"
  # Load and check required vars
  set -a; source "${AMUX_DIR}/server.env"; set +a
  for var in AMUX_URL AUTH_TOKEN; do
    if [ -z "${!var:-}" ]; then
      fail "server.env missing required: ${var}"
    else
      ok "server.env: ${var} set"
    fi
  done
  for var in AMUX_PUSHOVER_TOKEN AMUX_PUSHOVER_USER AMUX_BACKUP_REPO; do
    if [ -z "${!var:-}" ]; then
      warn "server.env optional-but-recommended missing: ${var}"
    fi
  done
fi

head "3. TLS cert not expired"
if [ -f "${AMUX_DIR}/tls/cert.pem" ]; then
  if openssl x509 -in "${AMUX_DIR}/tls/cert.pem" -checkend 604800 -noout 2>/dev/null; then
    ok "TLS cert valid for at least 7 more days"
  else
    if openssl x509 -in "${AMUX_DIR}/tls/cert.pem" -checkend 0 -noout 2>/dev/null; then
      warn "TLS cert expires within 7 days — renew soon"
    else
      fail "TLS cert is EXPIRED — server won't serve HTTPS"
    fi
  fi
else
  fail "TLS cert not found at ${AMUX_DIR}/tls/cert.pem"
fi

head "4. Database restored"
DB="${AMUX_DIR}/amux.db"
if [ ! -f "$DB" ]; then
  fail "database missing at ${DB} — restore step 3 (sqlite3 < amux.sql) not run"
else
  for tbl in issues threads messages schedules; do
    n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ${tbl}" 2>/dev/null || echo -1)
    if [ "$n" = "-1" ]; then
      fail "database table ${tbl} unreadable or missing"
    elif [ "$n" = "0" ]; then
      warn "database table ${tbl} has 0 rows (fresh install?)"
    else
      ok "database ${tbl}: ${n} rows"
    fi
  done
fi

head "5. Sessions"
SESSION_COUNT=$(ls "${AMUX_DIR}/sessions"/*.env 2>/dev/null | wc -l)
if [ "$SESSION_COUNT" = "0" ]; then
  fail "no session .env files at ${AMUX_DIR}/sessions/"
else
  ok "${SESSION_COUNT} session env-files present"
fi

head "6. Per-org SSH secrets + perms"
if ls "${AMUX_DIR}/orgs"/*.yml >/dev/null 2>&1; then
  for spec in "${AMUX_DIR}/orgs"/*.yml; do
    org=$(basename "$spec" .yml)
    ssh_dir="${AMUX_DIR}/orgs/${org}/secrets/ssh"
    if [ ! -d "$ssh_dir" ]; then
      warn "${org}: no secrets/ssh/ directory (agents can't push/pull)"
      continue
    fi
    ok "${org}: secrets/ssh/ present"
    # Perms — SSH refuses to use keys with loose perms
    ssh_perm=$(stat -c "%a" "$ssh_dir" 2>/dev/null || echo "?")
    if [ "$ssh_perm" != "700" ]; then
      fail "${org}: secrets/ssh/ perms ${ssh_perm} (must be 700) — SSH will refuse"
    fi
    # Check for at least one private key
    key_count=$(find "$ssh_dir" -type f ! -name '*.pub' ! -name 'config' ! -name 'known_hosts' 2>/dev/null | wc -l)
    if [ "$key_count" = "0" ]; then
      warn "${org}: no private keys in secrets/ssh/"
    fi
  done
else
  fail "no *.yml org specs at ${AMUX_DIR}/orgs/ — containers can't be rebuilt"
fi

head "7. Host jump-key for codegraph re-provisioning"
if [ -f "/etc/claude-deploy/keys/deploy_rsa" ]; then
  ok "/etc/claude-deploy/keys/deploy_rsa present"
else
  warn "/etc/claude-deploy/keys/deploy_rsa missing — per-org codegraph keys can't be pulled from 192.168.72.85 (see wiki/Codegraph-MCP.md)"
fi

head "8. Systemd services installed"
for svc in amux amux-serve amux-projects; do
  if systemctl list-unit-files "${svc}.service" 2>/dev/null | grep -q "${svc}.service"; then
    ok "${svc}.service registered"
  else
    warn "${svc}.service not registered (restore step 5 not run?)"
  fi
done

head "9. GitHub reachable from host (deploy_key auth)"
if [ -f "${HOME}/.ssh/deploy_key" ]; then
  if timeout 5 ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
     -i "${HOME}/.ssh/deploy_key" -T git@github.com 2>&1 | grep -q "Hi j3rm"; then
    ok "GitHub auth as j3rm via ~/.ssh/deploy_key"
  else
    warn "~/.ssh/deploy_key doesn't authenticate as j3rm on GitHub (rotate?)"
  fi
else
  warn "~/.ssh/deploy_key missing — host can't push amux backup or amux-server code"
fi

head "10. Working directories present"
if [ "$SESSION_COUNT" != "0" ]; then
  missing_dirs=0
  for env_file in "${AMUX_DIR}/sessions"/*.env; do
    dir=$(grep '^CC_DIR=' "$env_file" 2>/dev/null | sed 's/CC_DIR="//;s/"//' || echo "")
    if [ -n "$dir" ] && [ ! -d "$dir" ]; then
      missing_dirs=$((missing_dirs+1))
    fi
  done
  if [ "$missing_dirs" = "0" ]; then
    ok "every session's CC_DIR exists on disk"
  else
    fail "${missing_dirs} session(s) have CC_DIR pointing at a missing directory (restore step 6: clone repos)"
  fi
fi

echo
echo "─────────────────────────────────────────────────"
if [ "$FAIL" = "0" ] && [ "$WARN" = "0" ]; then
  echo "${G}All checks passed.${N} Safe to wake sessions."
  exit 0
elif [ "$FAIL" = "0" ]; then
  echo "${Y}Warnings: ${WARN} — review before waking sessions.${N}"
  exit 0
else
  echo "${R}FAILURES: ${FAIL} | WARNINGS: ${WARN}${N}"
  echo "Fix the failures above BEFORE waking sessions. Warnings are advisory."
  exit 1
fi
