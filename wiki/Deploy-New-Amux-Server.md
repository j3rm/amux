# Amux server deployment — reference documentation

Reference documentation of every script, config file, systemd unit, directory, and image that goes into an amux server. This page tells you WHAT the pieces are and WHERE they live; it does not walk you through commands. Anyone deploying — human or agent — reads this and figures out the order themselves based on the target environment.

**Scope.** Every artifact under this repo that ends up on a running amux host, plus every piece of state under `~/.amux/` that the server reads or writes at startup or runtime.

**Not in scope.** Ongoing operations after the server is live — see [Operations](Operations.md). The multi-agent orchestration layer on top — see [Orchestration-Architecture](Orchestration-Architecture.md).

---

## 1. What "amux" is, as installed on a host

| Layer | Component | Path on the running host |
|---|---|---|
| Server process | `amux-server.py` — single Python file, HTTPS on 8822, watches its own mtime for hot-reload | `/usr/local/bin/amux-server.py` (via `install.sh`) or `/opt/amux/amux-server.py` (cloud) or the repo checkout itself (Jeremy's desktop) |
| CLI | `amux` — bash wrapper around `curl` calls to the server, primary interface for agents | `/usr/local/bin/amux` |
| Remote CLI | `amux-remote` — same shape as `amux`, but points at a remote server via `~/.amux/remote.env` | `/usr/local/bin/amux-remote` |
| Container image | `amux-agent-base:latest` — Ubuntu + tmux + Node + Claude Code + Codex + a chown, built from `agent-container/Dockerfile` | Docker daemon on the host |
| Supervisor | `amux.service` — systemd unit that runs `amux-server.py` under `Restart=on-failure` | `/etc/systemd/system/amux.service` |
| State dir | `~/.amux/` — sessions, orgs, logs, uploads, threads, notes, shared creds, sqlite, tls, auth token | `/home/<user>/.amux/` (or `/root/.amux/` for the cloud VM which runs as root) |

The server is a single Python file. Everything else on this list is either the delivery mechanism (`install.sh`, systemd unit, docker image) or the state it operates on (`~/.amux/`). If you understand those five layers, you know the shape of the deployment.

---

## 2. Scripts in the repo — what each one does

### `install.sh` (repo root, 52 lines)

The local-install path. Copies three files into `$INSTALL_DIR` (defaults to `/usr/local/bin`) and verifies `tmux` + `python3` are on PATH. Uses `sudo` if the target dir isn't writable.

**Files copied:**
- `amux` → `/usr/local/bin/amux` (executable)
- `amux-server.py` → `/usr/local/bin/amux-server.py`
- `amux-remote` → `/usr/local/bin/amux-remote` (executable)

**Does NOT do:** create the state dir, seed config, install docker or node, register any systemd unit, build the container image, provision TLS. It is a copy-three-files installer, nothing more.

**Prints a "quick start" hint** telling the user to run `amux register`, `amux start`, `amux serve`. That workflow works for a single-user local install; it is NOT how the production deployments (Jeremy's desktop, the cloud VM) are wired.

### `cloud/setup.sh` (211 lines)

The GCP-VM bootstrap script. Runs as **root** via GCP's VM startup-script mechanism (idempotent — safe to re-run). Referenced from `cloud/main.tf` as the boot metadata.

**What it installs:**
- Base packages: `tmux git curl wget unzip jq htop python3 python3-pip build-essential ca-certificates gnupg`
- Node.js 22 LTS from NodeSource (for the version of Claude Code compatible with our workflows)
- Tailscale (for private-network reach to the dashboard)
- Claude Code CLI as a global npm package
- Standard `.tmux.conf` for root

**What it writes:**
- `/root/.amux/{tls,sessions,logs,memory,board}/` — state dir under root's home because the service User is root
- Tailscale TLS cert into `~/.amux/tls/`
- `/etc/systemd/system/amux.service` — the server supervisor
- `/etc/systemd/system/amux-watchdog.service` + `/usr/local/bin/amux-watchdog.sh` — connectivity watchdog that reboots the VM if the GCP metadata server goes dark for 5+ minutes
- `/etc/systemd/system/amux-health-watchdog.service` — Claude-powered application health watchdog (needs `scripts/watchdog.py` — see §3)
- `/etc/cron.weekly/amux-cert-renew` — Tailscale cert renewal

**What it does NOT do:** deploy `amux-server.py`. The unit file references `$AMUX_DIR/amux-server.py` but setup.sh only enables the service, does not start it. `deploy.sh` (below) does the file copy.

**Terraform var interpolation:** `${tailscale_auth_key}` in setup.sh is substituted by Terraform before the script runs — the raw script has that placeholder literal, not a resolved key.

### `cloud/deploy.sh` (154 lines)

The GCP-VM deploy driver. Runs on the operator's local machine (or in Scorpio's container), NOT on the target VM. Uses `terraform` + `gcloud compute` + IAP tunneling.

**What it does:**
1. Terraform init + apply (creates the VM from `cloud/main.tf`, seeds `setup.sh` as boot metadata)
2. Waits for Tailscale peer discovery (up to 10 min)
3. `gcloud compute scp` copies `amux-server.py` + `scripts/watchdog.py` into `/tmp/` on the VM, then `sudo cp`s into `/opt/amux/`
4. `sudo systemctl start amux` via `gcloud compute ssh`
5. Enables Tailscale Funnel for public iCal calendar reach
6. Smoke-tests `/api/sessions` and `/api/board`, creates a canary board item

**Prerequisites** (checked at top of script): `terraform`, `tailscale`, and the `amux-server.py` file relative to the script. Prompts for `PROJECT_ID` + `TS_KEY` if `terraform.tfvars` is absent.

**`--destroy` flag:** just runs `terraform destroy -auto-approve`.

### `cloud/deploy-gateway.sh` + `cloud/gateway/`

Deploys the Cloudflare Worker + Pages gateway that fronts the cloud amux server for auth-gated public access. **Not required** for a private (Tailscale-only) deployment. See the file itself for details; not covered further here.

### `cloud/setup-cloud.sh`

Older cloud-setup variant (Let's Encrypt via certbot, no Tailscale). Superseded by `setup.sh`. Retained for reference; do not use for new deploys.

### `backup/amux-backup.sh`

Backs up `~/.amux/` to a tarball, dumps SQLite separately, snapshots `~/.claude/projects/`. Referenced by `SCHED-39` inside amux itself. Not invoked at install time — scheduler runs it once amux is live.

### `agent-container/Dockerfile` (92 lines)

Recipe for `amux-agent-base:latest`. `docker build -t amux-agent-base:latest agent-container/` builds it. See [[reference-amux-image-defaults]] for what each RUN and ENV is defending against; do not modify without reading that memory.

**Base:** `python:3.11-slim`. **Adds:** apt: tmux/curl/git/node/npm/less/jq/sqlite3/vim-tiny. **npm -g:** `@anthropic-ai/claude-code @openai/codex`. **Chown:** `/usr/local/lib/node_modules` + `/usr/local/bin` to amux. **Env:** `TMUX_TMPDIR=/run/tmux`, `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1`. **User:** amux (uid 1000). **Entrypoint:** tini + `tail -f /dev/null` (containers stay alive; work is spawned via `docker exec`).

### `agent-container/example-org.yml` (68 lines)

Reference schema for `~/.amux/orgs/<name>.yml`. Real orgs have a similar shape; see §5 for the schema. Copy + edit for a new org.

### `scripts/watchdog.py`

Claude-powered application health watchdog referenced by `amux-health-watchdog.service` in the cloud setup. Independent of the `[4d]` in-server silently-dead detector — this one restarts the whole amux-server if `/health` fails to respond. Not covered further here.

---

## 3. Systemd units

Every unit below is created by the deploy path (setup.sh writes the cloud units; the local path writes them by hand or reuses an existing one). None of these are shipped as separate `.service` files in the repo.

### `amux.service` — the server supervisor

Two known-good variants:

**Cloud variant (from `cloud/setup.sh`):**
```ini
[Unit]
Description=amux server
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/amux
ExecStart=/usr/bin/python3 /opt/amux/amux-server.py
Restart=always
RestartSec=5
Environment=HOME=/root
StandardOutput=append:/var/log/amux.log
StandardError=append:/var/log/amux.log

[Install]
WantedBy=multi-user.target
```

**Jeremy's desktop variant** (as of 2026-06-18, the canonical system unit — see [Operations](Operations.md) "Supervisor — exactly ONE"):

```ini
[Unit]
Description=amux server
After=network.target

[Service]
Type=simple
User=jwesley
WorkingDirectory=/mnt/gitdata/amux
ExecStart=/usr/bin/python3 /mnt/gitdata/amux/amux-server.py
Restart=on-failure
RestartSec=5
Environment=HOME=/home/jwesley
StandardOutput=append:/home/jwesley/.amux/logs/server.log
StandardError=append:/home/jwesley/.amux/logs/server.log

[Install]
WantedBy=multi-user.target
```

**Which to use.** Match `User=`, `Environment=HOME=`, and `WorkingDirectory=` to whichever account owns the state dir. Root-owned state (`/root/.amux/`) → root user; jwesley-owned state (`/home/jwesley/.amux/`) → jwesley user. Mixing them is the #1 first-start failure mode.

**Hot-reload behavior.** `amux-server.py` watches its own mtime and `os.execv`-restarts on save (3s debounce). The systemd unit is only responsible for the initial start and for crash recovery; ordinary edits don't need `systemctl restart`.

### `amux-watchdog.service` (cloud-only)

Runs `/usr/local/bin/amux-watchdog.sh`. Reboots the VM if the GCP metadata server (`169.254.169.254`) is unreachable for 5+ minutes. Catches kernel-level network failures before Tailscale/SSH die. Not needed on-prem.

### `amux-health-watchdog.service` (cloud, optional)

Runs `python3 /opt/amux/scripts/watchdog.py`. Checks `/health` on the local amux server; if the server is unresponsive, delegates to Claude Code to diagnose + fix. Independent of the in-server watchdog. Not required for the server to function.

---

## 4. State directory — `~/.amux/`

Everything the server reads or writes at runtime lives here. Owner is the systemd unit's `User=`. Directory is created by the server on first start; scripts under §2 pre-create some subdirs but the server tolerates missing dirs by making them.

| Path | Contents | Notes |
|---|---|---|
| `~/.amux/amux.db` | SQLite database — board items, threads, notes, channels, skills, scheduler | Created on first start. Back this up. |
| `~/.amux/server.env` | Persistent env vars loaded at startup via `os.environ.setdefault` | Never commit. See §6. Chmod 600. |
| `~/.amux/auth_token` | Bearer token for `X-Amux-Auth` header on external API calls | Server generates on first start if missing. Loopback + docker-bridge sources bypass auth. |
| `~/.amux/tls/*.crt` + `*.key` | HTTPS server cert. Server picks the first pair alphabetically. | Self-signed / Tailscale / Let's Encrypt — see §7. |
| `~/.amux/sessions/<name>.env` | One file per session: `CC_DIR`, `CC_FLAGS`, `CC_ORG`, `CC_RUNTIME`, `CC_ARCHIVED`, `CC_AUTO_CONTINUE`, etc. | See §5 "Session env schema". |
| `~/.amux/sessions/<name>.meta.json` | Per-session metadata: conversation IDs, restart count, last-send tracking, codex_session_id | Written by the server; do not hand-edit while the session is running. |
| `~/.amux/orgs/<name>.yml` | Org container specs — mounts, sessions list, env, cross-mounts | See §5 "Org spec schema". Read on demand by `ensure_org_container`. |
| `~/.amux/orgs/<name>/home/` | Per-container shared `$HOME` — bind-mounted at `/home/amux/` inside the container. Holds `.claude/`, `.codex/`, `.claude.json`. | Login state persists here across restarts. |
| `~/.amux/orgs/<name>/secrets/` | Per-org SSH keys + gitconfig, mounted read-only at `/home/amux/.ssh/` | Only present for orgs whose spec declares those mounts. See RTG.yml / CD-*.yml for real examples. |
| `~/.amux/homes/<session>/` | Per-session `$HOME` when `CC_CLAUDE_AUTH_SHARED=0` | Container sees at `/homes/<session>/`. Normally unused — most sessions inherit the shared container home. |
| `~/.amux/shared-creds/personal.credentials.json` | Shared Anthropic OAuth for jeremywesley@gmail.com | Bind-mounted RW into every Jeremy-personal-account container. See [[reference-container-credential-ownership]]. |
| `~/.amux/shared-creds/nwddi.credentials.json` | Shared Anthropic OAuth for jeremy@nwddi.com | Bind-mounted RW into every NWDDI-account (CD-*) container. |
| `~/.amux/logs/<name>.log` | Per-session tmux scrollback tail (rolling ~10 MB) | Bind-mounted into containers at `/logs/<name>.log`. |
| `~/.amux/logs/server.log` | Server stdout+stderr via the systemd unit's StandardOutput | Rotated by systemd's default journal or logrotate — depends on the host. |
| `~/.amux/uploads/` | Thread attachments (dashboard uploads land here). @-mentions in agent messages reference these paths verbatim. | Bind-mounted READ-ONLY into every container at same path. See [[reference-amux-container-host-state-family]] § F. |
| `~/.amux/notes/`, `~/.amux/threads/`, `~/.amux/channels/` | On-disk cache for notes/threads/channels UI content | SQLite is the source of truth. |
| `~/.amux/memory/` | On-disk composed memory files for sessions (host-mode). Docker sessions have per-container homes so their memory lives in `~/.amux/orgs/<org>/home/.claude/`. | Written by `_write_claude_memory` at every session start. |
| `~/.amux/backups/` | Where `amux-backup.sh` writes tarballs | Sized by the schedule frequency. |

**Owner check.** After creating the state dir, `stat -c "%U %G %n" ~/.amux ~/.amux/*` should show the systemd unit's user consistently. Any `root root` entry produced by an early `sudo` needs `chown -R` before the server starts.

---

## 5. Config file schemas

### 5a. `~/.amux/sessions/<name>.env`

Shell-style KEY="value" file. Every real session in production has these keys; unset keys use documented defaults.

| Key | Values | Effect |
|---|---|---|
| `CC_DIR` | absolute path | Working directory the session's tmux `-c` is set to. Docker sessions must use a path that also exists inside the container (via mounts). |
| `CC_FLAGS` | e.g. `--model claude-fable-5 --dangerously-skip-permissions` | Passed to the provider CLI at spawn. YOLO flag is standard now. |
| `CC_AUTO_CONTINUE` | `"1"` / unset | If `"1"`, `[4d]` silently-dead detector auto-restarts the session on death. |
| `CC_ARCHIVED` | `"1"` / unset | If `"1"`, session doesn't start until `POST /api/sessions/<name>/wake` clears it. |
| `CC_ORG` | free-form string, e.g. `RTG` | Informational grouping shown in the UI. Independent of runtime. |
| `CC_RUNTIME` | unset (default) / `docker:<org>` | Runtime target. Unset = host tmux. Docker = spawn inside org container. |
| `CC_PROVIDER` | `claude` (default) / `codex` / `gemini` | Which CLI runs. Codex sessions need Codex CLI in the image (already installed). |
| `CC_CLAUDE_AUTH_SHARED` | `"1"` (default for docker) / `"0"` | `1` = inherit container's `/home/amux/.claude/`. `0` = per-session `HOME=/homes/<session>` override. |
| `CC_ICON` | one emoji | Dashboard session-card icon. |
| `CC_COLOR` | CSS color | Dashboard session-card accent. |
| `CC_DESC` | free-form | Description shown in UI + `amux sessions`. |
| `CC_CREATOR` | free-form | Who created the session (informational only). |
| `CC_BRANCH` | git branch name / `"none"` | Only meaningful for sessions using amux's optional branch-per-session feature. |

### 5b. `~/.amux/sessions/<name>.meta.json`

Managed by the server. Schema (subset — see `amux-server.py` for the full write logic):

```json
{
  "created_at": <unix-ts>,
  "creator": "<who-created>",
  "start_count": <int>,
  "last_started": <unix-ts>,
  "cc_session_name": "<name>",
  "cc_conversation_id": "<uuid>",     // Claude Code convo id to --resume
  "codex_session_id": "<uuid>",       // Codex session id, if provider=codex
  "last_send": <unix-ts>,
  "last_send_text": "<str>"
}
```

Editable by hand ONLY when the session is stopped. Common edit: clear `codex_session_id` after a container recreation (see [[reference-fleet-cutover-playbook]] § Codex stragglers).

### 5c. `~/.amux/orgs/<name>.yml`

Docker org container spec. Read on demand by `_load_product_spec(name)` — no server restart needed after edits, but running containers don't dynamically pick up mount changes (need `docker rm -f amux-org-<name>` + next-wake to reload).

**Minimum valid spec:**
```yaml
name: RTG
```
Every other field defaults per the loader.

**Real-world shape** (verbatim from `agent-container/example-org.yml`):
```yaml
name: RTG
image: amux-agent-base:latest

sessions:
  - RTG-Research
  - RTG-Dispatch
  # ...

mounts:
  - source: /mnt/gitdata/RemoteTechGroup
    target: /mnt/gitdata/RemoteTechGroup
    mode: rw
  # SHARED CRED — pick the file for the org's Anthropic account.
  - source: /home/jwesley/.amux/shared-creds/personal.credentials.json
    target: /home/amux/.claude/.credentials.json
    mode: rw
  # UPLOADS — required for thread attachment @-mentions to resolve inside container.
  - source: /home/jwesley/.amux/uploads
    target: /home/jwesley/.amux/uploads
    mode: ro

readonly_cross_mounts: []          # add cross-org RO mounts here when needed

env: {}                             # tmux -e VAR=value pairs, inherited by every session

session_home_dir_pattern: ~/.amux/homes/{session}   # default; rarely overridden
```

**Which credential file per org.** [[reference-container-credential-ownership]] is the source of truth. Summary: CD-* → `nwddi.credentials.json`; RTG/iSchedule/EmberCRM/ShareScore/Cypra/Personal/Scorpio → `personal.credentials.json`.

**The four bind mounts every org needs** (each defends against a specific defect — do not skip):
1. Working repo(s) at same path both sides (rw)
2. `/mnt/gitdata/amux` (ro) — so the `amux` CLI symlink resolves
3. Shared cred file → `/home/amux/.claude/.credentials.json` (rw)
4. `/home/jwesley/.amux/uploads` → same path (ro) — thread attachment @-mentions

See [Container-Isolation.md § How to add a new org](Container-Isolation.md#how-to-add-a-new-org) for the full checklist with WHY for each mount.

### 5d. `~/.amux/server.env`

Loaded at startup via `os.environ.setdefault(k, v)` — process env wins over file, and file wins over unset. Survives `os.execv` auto-restarts.

Known keys (subset — grep `amux-server.py` for `os.environ.get` for the full list):

| Key | Purpose | Required? |
|---|---|---|
| `AMUX_PUSHOVER_TOKEN` | Pushover app token for pushing alerts to Jeremy | Optional; alerts silently drop if unset |
| `AMUX_PUSHOVER_USER` | Pushover user key | Pair with token |
| `AMUX_S3_BUCKET`, `AMUX_S3_KEY`, `AMUX_S3_REGION` | S3 destination for the public iCal calendar feed | Optional; disables S3 upload if unset |
| `ANTHROPIC_API_KEY` | Fallback Claude auth when a session hasn't been `/login`'d | Optional; OAuth login is preferred |
| `AMUX_URL` | Base URL the server thinks of itself as (for outbound self-references) | Auto-detected if unset |
| `AMUX_COMMIT_GUARD` | `0` disables the commit-secrets pre-flight check | Default enabled; only disable if you know what you're doing |

Chmod 600, never commit.

---

## 6. Container image — `amux-agent-base:latest`

Built from `agent-container/Dockerfile`. `docker build -t amux-agent-base:latest agent-container/` from the repo root.

**What every container inherits (see [[reference-amux-image-defaults]] for full rationale — do not modify without reading that first):**

- **Base:** `python:3.11-slim`
- **Packages:** tmux, git, curl, node.js 22, npm, python3, sqlite3, less, jq, vim-tiny, openssh-client
- **Global CLIs:** `@anthropic-ai/claude-code`, `@openai/codex` (installed with `npm install -g` as root)
- **Ownership fix:** `/usr/local/lib/node_modules` and `/usr/local/bin` are chowned to `amux:amux` so the CLIs can auto-update in place. Without this, half the fleet crash-looped on 2026-07-10.
- **ENV `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1`** — forces Claude Code to native-scrollback so tmux capture-pane can see the conversation.
- **ENV `TMUX_TMPDIR=/run/tmux`** — keeps container tmux daemon distinct from host's.
- **User `amux` uid 1000** — matches host `jwesley` so bind-mounted files own correctly.
- **Entrypoint:** `tini` reaping zombies + `tail -f /dev/null` keeping the container alive. Every session is spawned via `docker exec amux-org-<X> tmux new-session ...`.

**Verify a build:**
```
docker run --rm amux-agent-base:latest sh -c \
  'claude --version && codex --version && stat -c "%U %G  %n" /usr/local/lib/node_modules /usr/local/bin && id'
```
Expect `amux amux` ownership and `uid=1000(amux)`. Anything else means the Dockerfile got reordered.

**When to rebuild:** see [[reference-fleet-cutover-playbook]] — a rebuild alone doesn't reach running containers; a fleet cutover is required.

---

## 7. TLS certificate — the three supported options

`amux-server.py` requires HTTPS. The server picks the first cert/key pair alphabetically in `~/.amux/tls/`. No config to select which; use only one pair.

| Option | Best for | How it lands in `~/.amux/tls/` |
|---|---|---|
| Self-signed OpenSSL | Local dev, internal-only hosts | `openssl req -x509 ... -keyout server.key -out server.crt`. Browsers warn. |
| Tailscale MagicDNS cert | Any host on a tailnet | `sudo tailscale cert --cert-file <host>.ts.net.crt --key-file <host>.ts.net.key <host>.ts.net`. Auto-trusted for tailnet peers. Cron `/etc/cron.weekly/amux-cert-renew` (written by `cloud/setup.sh`) renews. |
| Let's Encrypt | Public-DNS host, port 80 open | See `cloud/setup-cloud.sh` for the certbot flow. Auto-renews via `certbot`'s own systemd timer. |

Cloud VMs default to Tailscale. Jeremy's desktop uses self-signed. Both work.

---

## 8. Cross-references

- [Container-Isolation.md](Container-Isolation.md) — how the per-org container model works end-to-end, including "how to add a new session" and "how to add a new org" checklists that include the mounts every spec needs.
- [Operations.md](Operations.md) — supervision, hot-reload, backups, incident history for a running server.
- [Conversation-History-Locations.md](Conversation-History-Locations.md) — where Claude Code stores conversation JSONLs on host vs in containers.
- [[reference-amux-image-defaults]] — every Dockerfile chown/ENV with the incident it prevents.
- [[reference-container-credential-ownership]] — which shared cred file per org.
- [[reference-fleet-cutover-playbook]] — how to roll out a Dockerfile change (rebuild image + recreate every container).
- [[reference-amux-container-host-state-family]] — recurring host↔container bug shapes to check when writing any code that touches session I/O.

Anyone deploying a new amux server should read Container-Isolation.md, this page, and the two "reference" memories linked above before writing a single command. The order in which you invoke the pieces depends on the environment (fresh VM vs existing host vs cloud vs on-prem); no single order fits every case, so this page deliberately does not prescribe one.
