# Deploy a new amux server — Scorpio playbook

> **Who this is for.** Scorpio, primarily — you have `govc` for on-prem VM provisioning, the `/etc/claude-deploy/deploy_rsa` SSH key that's already trusted on the provisioned VMs, and `/mnt/gitdata/amux` mounted read-only in your container. This playbook walks you through provisioning a fresh Ubuntu VM, installing amux on it, and getting the dashboard reachable — end to end, no external help needed.
>
> **What "amux server" means here.** A single Ubuntu host running `amux-server.py` under systemd, with docker installed for per-org containers, a persistent `~/.amux/` state dir, and the dashboard exposed at `https://<host>:8822`. This is the same setup we run on the Jeremy desktop and on `amux-dev` cloud VM.
>
> **When to run this playbook.** Two entry points:
> 1. **Fresh VM path** — provision + install. Scorpio's happy path. Starts at §1.
> 2. **Existing host path** — someone already gave you a Linux box with SSH access; skip to §3.
>
> **When NOT to run this playbook.** Do not run against a host that's already running amux — you'll clobber the state dir. Check `curl -sk https://<host>:8822/api/sessions` first; if it responds, the host has amux and this playbook is the wrong tool.

## 0. Ground rules — read before you start

- **Never proceed on assumption.** If a step below says a file exists at a path, `ls` it before referencing it. This playbook was written 2026-07-10; layouts drift.
- **All actions on the target host go through SSH** with the deploy key. Do not paste `sudo` commands into the wrong shell — you have shells open on your container, your VMs, and possibly Jeremy's desktop.
- **Never commit `.credentials.json` or `auth_token` files to any git repo.** The state dir contains OAuth tokens; keep it off git.
- **Report back on the board when done.** PATCH your assigned board item to `done` with the dashboard URL in the description. See CLAUDE.md § Inter-Agent Communication.

---

## 1. Provision the VM (Scorpio's on-prem happy path)

### Required inputs — ask Jeremy before starting if any of these aren't in your task

| Input | Where you'd get it | Notes |
|---|---|---|
| VM name (short, hostname-legal) | Task description | e.g. `amux-clientname` |
| vCenter template | `/etc/claude-deploy/vm-templates.md` if it exists, else ask | Default: `ubuntu-22.04-amux-base` if provisioned; else `ubuntu-22.04` |
| RAM / CPU / disk | Task description | Default for a small fleet: 4 vCPU, 8 GB RAM, 60 GB disk. For 20+ agents: 8 vCPU, 16 GB RAM, 100 GB disk. |
| Static IP or DHCP | Task description | Static preferred for a durable dashboard URL |
| Which Anthropic account the fleet will log in as | Task description | See [[reference-container-credential-ownership]] — one shared cred file per account |

### 1a. Clone from template + boot

```bash
# vCenter deploy the template. Path pattern below matches our vCenter layout.
export GOVC_URL="https://vcenter.internal"     # or whatever /etc/claude-deploy points to
source /etc/claude-deploy/govc.env             # sets GOVC_USERNAME, GOVC_PASSWORD, GOVC_INSECURE

VM_NAME="amux-<clientname>"
TEMPLATE="ubuntu-22.04-amux-base"              # verify: govc ls /Datacenter/vm/templates/

govc vm.clone \
  -vm "/Datacenter/vm/templates/$TEMPLATE" \
  -on=true \
  -c=4 -m=8192 \
  "$VM_NAME"

# Grab its IP (wait for VMware Tools to report — up to ~90s after power-on)
for i in $(seq 1 30); do
  IP=$(govc vm.info -json "$VM_NAME" | jq -r '.virtualMachines[0].guest.ipAddress // empty')
  [ -n "$IP" ] && break
  sleep 5
done
echo "VM IP: $IP"
```

### 1b. Verify SSH works with the deploy key

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i /etc/claude-deploy/deploy_rsa \
    "jwesley@$IP" 'hostname && whoami && uname -a'
```

You should see the VM's hostname and `jwesley`. If not: check that the template baked in the deploy_rsa.pub as an authorized_keys entry for jwesley — if not, ask Jeremy which key to use for this template.

**Shortcut:** stash the SSH invocation as a helper for the rest of the playbook:

```bash
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /etc/claude-deploy/deploy_rsa jwesley@$IP"
$SSH 'whoami'   # sanity
```

---

## 2. Bootstrap the OS

Everything in §2 runs via `$SSH '...'`.

### 2a. Base packages

```bash
$SSH 'sudo apt-get update -qq && sudo apt-get install -y -qq \
  tmux git curl wget unzip jq htop \
  python3 python3-pip python3-yaml \
  build-essential ca-certificates gnupg \
  less vim-tiny sqlite3 openssh-client'
```

### 2b. Node.js 22 (for Claude Code + Codex — same version as the container image uses)

```bash
$SSH 'if ! command -v node >/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
  sudo apt-get install -y -qq nodejs
fi
node --version && npm --version'
```

### 2c. Docker (for the per-org containers)

```bash
$SSH 'if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker jwesley
sudo systemctl enable --now docker
docker --version'
```

**You must log out and back in** for the docker group membership to take effect — or use `sudo` for docker calls this session. New SSH sessions after the group add will have docker in their group set.

### 2d. Directory layout

```bash
$SSH 'mkdir -p ~/.amux/{sessions,logs,memory,orgs,uploads,shared-creds,notes,threads,backups,tls}
      ls -la ~/.amux/'
```

---

## 3. Install amux itself

### 3a. Get the code onto the box

You have two options — pick based on what the target host can reach.

**Option A — clone from the fork (github.com/j3rm/amux) via SSH:**
```bash
$SSH 'cd ~ && git clone git@github.com:j3rm/amux.git amux || (cd amux && git pull)'
$SSH 'cd ~/amux && git checkout jwesley-main'
```
Requires an SSH deploy key on the target host with read access to the j3rm/amux repo. If the target doesn't have one, use Option B.

**Option B — rsync from your own container's read-only mount:**
```bash
# From inside your Scorpio container, push /mnt/gitdata/amux to the target:
rsync -a -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /etc/claude-deploy/deploy_rsa" \
      --exclude='.git/objects/pack' \
      /mnt/gitdata/amux/ jwesley@$IP:~/amux/
```
This copies the working tree. You lose git history on the target but the server runs fine without it. Suitable for air-gapped hosts.

### 3b. Run the install script

The repo ships an `install.sh` at the root that copies `amux`, `amux-server.py`, and `amux-remote` into `/usr/local/bin` and verifies tmux + python are available.

```bash
$SSH 'cd ~/amux && sudo ./install.sh'
$SSH 'which amux && amux --help | head -5'
```

### 3c. Deploy the systemd unit

There is no shipped `.service` file in the repo — it's baked into `cloud/setup.sh` for the GCP path, and Jeremy's desktop uses a system unit at `/etc/systemd/system/amux.service`. Write one:

```bash
$SSH 'sudo tee /etc/systemd/system/amux.service >/dev/null <<UNIT
[Unit]
Description=amux server
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=jwesley
Group=jwesley
WorkingDirectory=/home/jwesley/amux
ExecStart=/usr/bin/python3 /home/jwesley/amux/amux-server.py
Restart=on-failure
RestartSec=5
Environment=HOME=/home/jwesley
StandardOutput=append:/home/jwesley/.amux/logs/server.log
StandardError=append:/home/jwesley/.amux/logs/server.log
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT'
$SSH 'sudo systemctl daemon-reload && sudo systemctl enable amux.service'
```

**Do not start amux yet.** Startup expects a few config files that we haven't created; if you start it now, it'll create defaults you'll have to overwrite. Continue to §4.

---

## 4. Config that must exist before first start

### 4a. `~/.amux/server.env`

Persistent env vars for the server. Loaded at startup so process-level env always wins. **Never commit this file.**

```bash
$SSH 'cat > ~/.amux/server.env <<ENV
# Optional. Uncomment + fill for the features you want:
# AMUX_PUSHOVER_TOKEN=<pushover-app-token>
# AMUX_PUSHOVER_USER=<pushover-user-key>
# AMUX_S3_BUCKET=<bucket-for-ical-calendar-feed>
# AMUX_S3_KEY=amux/calendar.ics
# AMUX_S3_REGION=us-east-2
# ANTHROPIC_API_KEY=<only-if-not-using-oauth-login-for-agents>
ENV
chmod 600 ~/.amux/server.env
ls -la ~/.amux/server.env'
```

Ask Jeremy for the Pushover token/user if the fleet on this host should page him.

### 4b. Auth token

`amux-server.py` generates `~/.amux/auth_token` on first start if absent — you don't have to seed it. **But** you do need to know the token to hit the API from other tools. After first start, retrieve it:

```bash
$SSH 'cat ~/.amux/auth_token'
```

### 4c. TLS certificate

`amux-server.py` requires an HTTPS cert. Options:

**A. Self-signed (fastest, use for internal-only hosts):**
```bash
$SSH 'openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
       -keyout ~/.amux/tls/server.key -out ~/.amux/tls/server.crt \
       -subj "/CN=$(hostname)"
       ls -la ~/.amux/tls/'
```
Dashboard will show a browser warning; agents that hit the API with `curl -sk` don't care.

**B. Tailscale cert (best for boxes on a Tailscale network):**
Install Tailscale first (`curl -fsSL https://tailscale.com/install.sh | sh`), join it (`tailscale up`), then:
```bash
$SSH 'TS_HOST=$(tailscale status --self --json | python3 -c "import sys,json; print(json.load(sys.stdin)[\"Self\"][\"DNSName\"].rstrip(\".\"))")
      sudo tailscale cert --cert-file ~/.amux/tls/$TS_HOST.crt --key-file ~/.amux/tls/$TS_HOST.key $TS_HOST'
```
Browser-trusted automatically for anyone on the tailnet.

**C. Let's Encrypt (only if this box has a public DNS name and port 80 open):**
Not covered here — see `cloud/setup-cloud.sh` for the certbot flow if that's the target.

### 4d. Shared credential files

Before an org container can log its agents in, you need a shared credential file for each Anthropic account that the fleet will use. See [[reference-container-credential-ownership]] for the shape.

```bash
$SSH 'touch ~/.amux/shared-creds/personal.credentials.json ~/.amux/shared-creds/nwddi.credentials.json
      chmod 600 ~/.amux/shared-creds/*.credentials.json
      ls -la ~/.amux/shared-creds/'
```

**Both start empty.** They will be populated after §7 (per-org `/login`). Do not attempt to copy Jeremy's credentials from your Scorpio container into these files — they're bound to different Anthropic accounts by design.

### 4e. Ownership sanity check

Everything under `~/.amux/` must be owned by `jwesley` (uid 1000). The container image assumes uid 1000 = amux user, so bind-mounted files land with matching owner. Verify:

```bash
$SSH 'ls -la ~/.amux/ | head
      stat -c "%U %G %n" ~/.amux ~/.amux/shared-creds ~/.amux/orgs 2>&1'
```

If any of these show `root root`, chown them: `sudo chown -R jwesley:jwesley ~/.amux/`

---

## 5. Build the container base image

Every session runs inside a per-org docker container built from `amux-agent-base:latest`. Build it now so the first session wake finds it.

```bash
$SSH 'cd ~/amux
      docker build -t amux-agent-base:latest agent-container/
      docker run --rm amux-agent-base:latest sh -c "claude --version && codex --version && stat -c \"%U %G  %n\" /usr/local/lib/node_modules /usr/local/bin"'
```

You should see:
- `2.1.<some-version> (Claude Code)`
- Codex version line
- `amux amux  /usr/local/lib/node_modules` and `amux amux  /usr/local/bin`

The `amux:amux` ownership is a durable Dockerfile fix (see [[reference-amux-image-defaults]]) — if it says `root root`, the Dockerfile drift-corrupted; grep the Dockerfile for the chown line and confirm it lives AFTER `useradd -m amux`.

---

## 6. Start amux for the first time

```bash
$SSH 'sudo systemctl start amux.service
      sleep 5
      sudo systemctl is-active amux.service
      curl -sk -o /dev/null -w "HTTP %{http_code}\n" https://localhost:8822/api/sessions
      cat ~/.amux/auth_token'
```

Expected: `active`, `HTTP 200`, and the auth token printed. If `is-active` says `failed`, check `~/.amux/logs/server.log` — most first-start failures are TLS cert path mismatch or missing `~/.amux/server.env`.

**From your Scorpio container, hit the fresh dashboard:**
```bash
export AMUX_URL="https://$IP:8822"
curl -sk "$AMUX_URL/api/sessions" | python3 -m json.tool | head -20
```

Empty session list (`[]`) is expected — no sessions yet. Server is alive.

---

## 7. Register the first org and its sessions

Follow [Container-Isolation.md § How to add a new org](Container-Isolation.md#how-to-add-a-new-org) for the org spec YAML. Bare minimum for a working first org:

```bash
$SSH 'cat > ~/.amux/orgs/FirstOrg.yml <<YAML
name: FirstOrg
image: amux-agent-base:latest
sessions:
  - FirstOrg-Main
mounts:
  - source: /mnt/data/FirstOrg
    target: /mnt/data/FirstOrg
    mode: rw
  - source: /home/jwesley/amux
    target: /mnt/gitdata/amux
    mode: ro
  - source: /home/jwesley/.amux/shared-creds/personal.credentials.json
    target: /home/amux/.claude/.credentials.json
    mode: rw
  - source: /home/jwesley/.amux/uploads
    target: /home/jwesley/.amux/uploads
    mode: ro
readonly_cross_mounts: []
env:
  MIXPEEK_API_KEY: ""
YAML

# The session env file
cat > ~/.amux/sessions/FirstOrg-Main.env <<ENV
CC_DIR="/mnt/data/FirstOrg"
CC_ORG="FirstOrg"
CC_RUNTIME="docker:FirstOrg"
CC_FLAGS="--dangerously-skip-permissions"
CC_AUTO_CONTINUE="1"
CC_DESC="Main session for FirstOrg"
ENV'
```

Wake the session — this triggers `ensure_org_container` which creates `amux-org-FirstOrg` from the base image and spawns a tmux inside:

```bash
curl -sk -X POST "$AMUX_URL/api/sessions/FirstOrg-Main/wake" -w 'HTTP %{http_code}\n'
sleep 15
curl -sk "$AMUX_URL/api/sessions/FirstOrg-Main/peek" | python3 -c "
import json,sys,re
d = json.load(sys.stdin)
t = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', d.get('output') or d.get('screen',''))
print('\n'.join(t.rstrip().split('\n')[-15:]))
"
```

You should see a Claude Code welcome banner asking to `/login` (the shared cred file is empty). **Jeremy has to do this login step interactively** — you cannot log in on his behalf. Report back on the board with:
- The dashboard URL (`https://<IP>:8822`)
- The auth token from `~/.amux/auth_token`
- Which session needs `/login` and which account (`jeremy@nwddi.com` or `jeremywesley@gmail.com`)

Jeremy attaches to the session (via dashboard or `amux-remote attach`), runs `/login`, and the shared cred file populates. Every subsequent session in the same org container inherits the login.

---

## 8. Verify + hand back

```bash
# From your Scorpio container:
echo "=== amux is up at $AMUX_URL ==="
curl -sk "$AMUX_URL/api/sessions" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Sessions registered: {len(d)}')
for s in d: print(f'  {s[\"name\"]:<30} running={s.get(\"running\")} archived={s.get(\"archived\")}')
"
echo "=== systemd status ==="
$SSH 'systemctl is-active amux.service && systemctl is-active docker.service'
echo "=== disk headroom ==="
$SSH 'df -h / && docker system df'
```

**Hand-back message to post on the board when done** (PATCH your assigned item to `done`, put this in `desc`):

```
Amux server deployed on <VM_NAME> at <IP>.
- Dashboard:  https://<IP>:8822
- Auth token: <cat ~/.amux/auth_token output>
- Systemd:    amux.service (enabled, active)
- Base image: amux-agent-base:latest built + verified
- First org:  <OrgName> registered — session <SessionName> awaiting Jeremy's /login as <account>
- Disk:       <df -h / output for root LV>
```

## 9. Common failures — expect these, don't panic

| Symptom | Root cause | Fix |
|---|---|---|
| `sudo systemctl start amux` → failed, log says `PermissionError: [Errno 13] Permission denied: '/root/.amux/...'` | Systemd unit user is `root` but the state dir is under `/home/jwesley/.amux/`, or vice versa | Match `User=`, `Environment=HOME=`, and `WorkingDirectory=` in the unit to the state dir owner |
| Session wake returns 500, log says `docker: Error response from daemon: Ports are not available` | Something else already bound `:8822` on the host | `ss -tlnp \| grep 8822` — kill the imposter, or change `AMUX_PORT` in `server.env` |
| Session comes up but shows `bash: claude: command not found` in peek | The container image wasn't built with amux ownership on `/usr/local/bin` | See [[reference-amux-image-defaults]] § chown — the Dockerfile line must run after `useradd`. Rebuild the image + `docker rm -f amux-org-<org>` + wake. |
| Session comes up with `Auto-update failed: no write permission to npm prefix` | Same as above — chown missing | Rebuild image, cycle containers per [[reference-fleet-cutover-playbook]] |
| Dashboard peek shows blank screen even though the session is at a claude prompt | Claude Code entered alternate-screen mode; `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1` isn't set in the image | Rebuild image (Dockerfile has this ENV baked in as of 2026-07-10). If build predates that fix, add it and rebuild. |
| First session wake succeeds but subsequent parallel wakes 500 with "container not ready" | `ensure_org_container` race — happens when >1 session in the same org tries to spawn its container simultaneously | Wake ONE session per org serially first, THEN parallel-wake the rest. See [[reference-fleet-cutover-playbook]] § step 5. |
| SSL error hitting dashboard, `SSLError: WRONG_VERSION_NUMBER` | HTTP request against HTTPS port | Always use `https://` and `curl -sk`. Never `http://` for the amux server. |
| Claude Code errors on `/login` with "cannot open browser" | The session is inside a container, no browser | This is expected — Claude Code's OAuth flow prints a URL. Jeremy opens the URL on his laptop, pastes the code back into the session. |

## 10. Reference — related pages

- [Container-Isolation.md](Container-Isolation.md) — Full explanation of the per-org container model this playbook wires up.
- [Operations.md](Operations.md) — Once amux is running, this is the ongoing operational runbook (supervision, hot-reload, backups, incident history).
- [[reference-container-credential-ownership]] — Shared cred file architecture. Read before adding a second org that uses a different Anthropic account.
- [[reference-amux-image-defaults]] — What the container image bakes in and why. Read before touching the Dockerfile.
- [[reference-fleet-cutover-playbook]] — What to do when the image is rebuilt post-deploy.
- [Conversation-History-Locations.md](Conversation-History-Locations.md) — Where Claude Code stores conversation JSONLs (host vs container).
