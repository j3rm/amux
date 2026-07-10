# Operations runbook

How to run, supervise, deploy, and recover the amux server, plus the adjacent
systems (skills library, backups) and the incident history that shaped today's
setup.

## Process & supervision

- Server: `/usr/bin/python3 /mnt/gitdata/amux/amux-server.py`, WorkingDirectory
  `/mnt/gitdata/amux`, listens on `:8822` (HTTPS). Dashboard URL:
  `https://localhost:8822` locally, `https://amuxcc.embercrm.com:8822` remote.
- **Hot-reload:** the server watches its own mtime and `os.execv`-restarts
  in-place on file save (3s debounce). So saving `amux-server.py` IS a live
  deploy. **Always verify the reload took** — a known failure mode is the
  watcher missing a write or the execv racing:
  ```bash
  pgrep -f '^/usr/bin/python3 /mnt/gitdata/amux/amux-server.py' | xargs ps -o pid,lstart -p
  stat -c '%y' /mnt/gitdata/amux/amux-server.py
  # process start MUST postdate the file mtime; if not, touch the file or restart
  ```

### Supervisor — exactly ONE (this matters)

There are two possible supervisors; **run only one**:
- **System unit** `/etc/systemd/system/amux.service` (`Restart=on-failure`).
  As of 2026-06-18 this is the **active, canonical** supervisor
  (`sudo systemctl enable --now amux.service`). Survives reboot/logout without
  a login session.
- **User unit** `~/.config/systemd/user/amux.service` (needs `loginctl
  enable-linger jwesley` and a running `systemd --user`). Was canonical
  earlier; its manager lapsed (see incident below).

Why only one: two supervisors each start a server. Historically both bound
:8822 silently (because `SO_REUSEPORT=True`) and ran **duplicate schedulers** →
schedules double-fired, `/send` arrived twice, dashboard state was inconsistent.
Fixed in `f435e80` (`allow_reuse_port=False`) so a second instance now **fails
to bind** instead of silently double-running — the duplicate-UX bug can't recur
the same way. But still keep one supervisor so the other doesn't sit failed.

Health check:
```bash
systemctl is-active amux.service
pgrep -fc '^/usr/bin/python3 /mnt/gitdata/amux/amux-server.py'   # must be 1
ss -tlnp | grep -c 8822                                          # must be 1
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8822/api/sessions
```

### Manual restore (no supervisor available)
Safe stopgap (no auto-restart): 
```bash
HOME=/home/jwesley setsid nohup /usr/bin/python3 /mnt/gitdata/amux/amux-server.py \
  >> ~/.amux/logs/server.log 2>&1 </dev/null &
```
Then re-establish a supervisor and `kill` the nohup so systemd binds the port.

## Deploy

"Deploy" in this fork:
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` (syntax).
2. `git add amux-server.py && git commit -m "..."`.
3. `git push fork jwesley-main` (origin/mixpeek is read-only — pushes denied).
4. Verify hot-reload took (see above). The save already deployed live; the push
   is the durable backup.

## Config — `~/.amux/server.env`

Persistent server env (loaded at startup, overrides process env). Holds:
`ANTHROPIC_API_KEY`, `AMUX_URL`, `AMUX_PUSHOVER_TOKEN`/`_USER`,
`AMUX_COMMIT_GUARD` (=0, disabled), S3 calendar keys, etc. After editing,
`touch amux-server.py` to reload. Never commit it (secrets).

## Per-session env — `~/.amux/sessions/<name>.env`
`CC_DIR`, `CC_FLAGS` (model + `--dangerously-skip-permissions`),
`CC_AUTO_CONTINUE`, `CC_ICON`, `CC_COLOR`, `CC_ORG`, `CC_DESC`. Conversation
resume identity is in `<name>.meta.json` (`cc_session_name`,
`cc_conversation_id`).

## Backups
- `amux-backup.sh` — backs up `~/.amux/` (DB, sessions, notes, server.env, tls,
  auth_token), a SQLite dump, `~/.claude/projects/` conversation JSONLs, and
  system files. Schedule: `SCHED-39` ("AMUX system backup", every 6h, silent).
- **Not in git** but critical on disk loss: agent role files under
  `/mnt/gitdata/<Org>/.agents/` (org roots aren't repos) and schedule prompts
  in `~/.amux/amux.db`. The [Orchestration-Architecture](Orchestration-Architecture.md)
  page is the rebuild spec for those.

## Shared Zoho skills library
- Repo: `/mnt/gitdata/agent-skills` (git), symlinked to `~/.claude/skills` so
  **every** agent on the box auto-loads it at session start (no copying).
- Skills: `zoho-auth`, `zoho-books`, `zoho-crm`, `zoho-crm-functions`,
  `zoho-analytics`, `zoho-projects` — battle-tested API knowledge harvested from
  real migrations. Each carries a write-back rule; `SCHED-42` is the weekly
  curation pass (Cypra-PAA). Never store token values in skills/notes — they
  live in `~/.claude/.credentials.json`.

## Browser automation
`/chrome-cdp` connects to the user's live Chrome over CDP (real tabs/cookies).
Requires Chrome remote debugging + Node 22+.

## Incident history (root causes, so they don't recur)
- **Duplicate servers** (06/12): two supervisors + `SO_REUSEPORT` → double
  schedulers. Fix: `allow_reuse_port=False` + one supervisor.
- **Fabricated `done`** (06/12): idle auto-completed all open items. Fix: no-op
  + PATCH-only status + per-wake guards.
- **Claim-then-stall** (06/15): blanket `RD-*` exclusion blocked actionable
  routing directives. Fix: title-based exclusion + a `doing → cut worker task`
  step.
- **Over-escalation** (06/17): PASS-vs-PASS-WITH-WARNINGS escalated; settled
  items reprocessed. Fix: acceptance-based resolution + settled-item guard.
- **Peek freeze** (06/18): scroll-lock latched on mobile. Fix: resume-release +
  programmatic-scroll guard + flush-on-unlock + relaxed threshold.
- **Supervisor outage** (06/18): user systemd manager was down + system unit
  disabled → server self-execv'd on save with nothing to catch it. Fix:
  re-enabled the system unit as the single supervisor.
- **Credential wipe cascade — NWDDI side** (07/10 23:32 UTC): all 10 CD-*
  containers lost their `.claude/.credentials.json` at the same moment.
  Root cause: Anthropic DOES rotate the OAuth refresh token on every access
  refresh (contrary to earlier assumption). Every CD-* container held an
  independent copy of the same NWDDI refresh token; when `amux-helper`
  refreshed, all container copies invalidated at once. Fix: switch every org
  container from per-container credential file to a shared bind-mounted file
  (`~/.amux/shared-creds/nwddi.credentials.json` for NWDDI, `personal.credentials.json`
  for Jeremy-personal). See Container-Isolation.md § Shared credential files.
- **Credential wipe cascade — Gmail side** (07/10, during fleet reboot): shared
  `personal.credentials.json` got wiped when ~40 Gmail-side sessions all fired
  their initial token refresh simultaneously; one won the race, the rest wrote
  stale-in-memory copies over the shared file. Recovered by copying a
  still-valid credential from a container (Scorpio) that hadn't been touched.
  Long-term: stagger session wake after a fleet cutover.
- **Claude Code auto-update crash-loop** (07/10 03:00 UTC): iSchedule-Auth,
  iSchedule-Client_Web, iSchedule-Provider (and others) crash-looped at
  startup. Root cause: `npm install -g @anthropic-ai/claude-code` failed
  EACCES on `/usr/local/lib/node_modules` (root-owned in image, amux user
  can't write), and Claude Code **exits to bash** on the failure instead of
  warning. Fix: `chown -R amux:amux /usr/local/lib/node_modules /usr/local/bin`
  baked into the Dockerfile so amux user can auto-update in place. See
  Container-Isolation.md § What the amux-agent-base image gives you.
- **Root LV disk-full** (07/10 01:00 UTC): `/dev/mapper/ubuntu--vg-ubuntu--lv`
  hit 100% during a runtime `chown -R` across running containers. Root cause:
  the chown triggered docker's copy-on-write to duplicate ~1.1GB of
  `node_modules` into each container's writable layer, ballooning fleet-wide
  overlay from ~30MB to ~11GB in seconds. This cascaded into blocking Claude
  Code's own tmpfs at `/tmp/claude-<uid>/` (0MB free), which stopped `amux-helper`
  from running any command until Jeremy grew the LV and manually pruned images.
  Fix: recreate all containers so their writable layers reset (~11GB reclaim),
  bake the chown into the image so it lives in the shared image layer instead
  of the per-container writable layer, and monitor `docker ps --size` for
  containers hitting `>1GB`. See Container-Isolation.md § Fleet-wide container
  recreation.
- **Fullscreen alt-screen breaks peek** (07/10): some Claude Code sessions ended
  up in the terminal alternate-screen buffer, which made `tmux capture-pane`
  return an empty screen with just the input prompt — peek text was garbled,
  SMS reply detection lost the conversation context. Fix:
  `ENV CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1` in the Dockerfile so every claude
  spawn is in native-scrollback mode.
