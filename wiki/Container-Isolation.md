# AMUX per-org container isolation — ops reference

> The architecture is: **AMUX server runs on host, spawns tmux+claude INSIDE per-org containers.** Each org (RTG / iSchedule / EmberCRM / ShareScore / CD-*) is one long-lived Docker container. Every AMUX agent for that org is a tmux session inside that one container. `CC_RUNTIME=docker:<org>` on a session's env file is the switch that routes it. Sessions with no `CC_RUNTIME` keep running on host as before.

## Reading map — where to look first

- **This file** — how it works, where files live, how to extend/debug.
- **[[amux-isolation-plan]]** — decision history, phase-by-phase commit log, known limitations, decision quotes from Jeremy.
- **`fork/jwesley-main` on github.com/j3rm/amux** — source. Look at commits `feat(isolation):` (Phase 1a → 2g).
- **`~/.amux/orgs/*.yml`** — one file per org; edit these to change mounts/env/sessions.
- **agent-container/Dockerfile in the amux repo** — the image every org runs.
- **[[amux-isolation-plan]] "Ready-state before first wake"** — feature-by-feature what's wired up.

## Orgs at a glance

| Org | Container | Sessions | Working repos mounted |
|---|---|---|---|
| RTG | `amux-org-RTG` | 13 (Research/Dispatch + Audit-Codex + Audit-Opus48 + 8 workers + Artemis) | `/mnt/gitdata/RemoteTechGroup` rw, `/mnt/gitdata/RTG-AccountingMigration` rw, `/mnt/gitdata/ACT_CRM` rw |
| iSchedule | `amux-org-iSchedule` | 8 | `/mnt/gitdata/iSchedule` rw |
| EmberCRM | `amux-org-EmberCRM` | 13 | `/mnt/gitdata/EmberCRM` rw |
| ShareScore | `amux-org-ShareScore` | 2 | `/mnt/gitdata/ShareScore` rw |
| CD-AirCom | `amux-org-CD-AirCom` | 2 (Analytics + Catalyst) | `/mnt/gitdata/ClientData/AirCom` rw |
| CD-Classic-Pianos | `amux-org-CD-Classic-Pianos` | 1 | `/mnt/gitdata/ClientData/Classic Piano` rw |
| CD-In-DepthEvents | `amux-org-CD-In-DepthEvents` | 1 | `/mnt/gitdata/ClientData/In-DepthEvents` rw |
| CD-MyOwnerCircle | `amux-org-CD-MyOwnerCircle` | 1 | `/mnt/gitdata/ClientData/My Owner Circle` rw |
| CD-NPP | `amux-org-CD-NPP` | 1 | `/mnt/gitdata/ClientData/NPP` rw |
| CD-NRT | `amux-org-CD-NRT` | 1 | `/mnt/gitdata/ClientData/NRT` rw |
| CD-Shurloc | `amux-org-CD-Shurloc` | 1 | `/mnt/gitdata/ClientData/Shurloc` rw |
| CD-SurfPrep | `amux-org-CD-SurfPrep` | 1 | `/mnt/gitdata/ClientData/SurfPrep` rw |
| CD-Wattco | `amux-org-CD-Wattco` | 1 | `/mnt/gitdata/ClientData/Wattco` rw |
| CD-Wyoming | `amux-org-CD-Wyoming` | 1 | `/mnt/gitdata/ClientData/WyomingCorpServices` rw |

Every org container also gets `/mnt/gitdata/amux` **read-only** so the `amux` CLI (symlinked at `/usr/local/bin/amux → /mnt/gitdata/amux/amux`) resolves.

**Host-mode sessions (unchanged, run as jwesley with full host access):** `amux-helper`, `Cypra`, `Cypra-EmailAgent`, `Cypra-PAA`, `AMUX-Watchdog`, `Scorpio`, `RTG-VS2017` (remote), plus currently-unassigned: `LYNQ-GPS`, `N8N`, `SmarterTrackResearch`, `WordpressDesign`, `Vid-TM-Builder`, `Vid-TM-Orchestrator`, `Vid-TM-QC`.

## Where every file lives (host ↔ container)

```
HOST                                          CONTAINER (bind-mounted / env-set)
────────────────────────────────────────────────────────────────────────────────
~/.amux/orgs/<org>.yml                (read at spawn — never mounted)
~/.amux/orgs/<org>/home/              /home/amux/                (rw)
  ├── .claude/                                  ~/.claude/               ← shared login
  │     ├── .credentials.json                     └── OAuth token per org
  │     └── projects/<slug>/*.jsonl               └── conversation history
  └── .codex/config.toml                        ~/.codex/config.toml     ← codex trust

~/.amux/homes/<session>/                      /homes/<session>/          (rw)
  └── .claude/                                  used ONLY if CC_CLAUDE_AUTH_SHARED=0
                                                (per-session opt-out from shared login)

~/.amux/logs/<session>.log                    /logs/<session>.log        (rw, same inode)
                                                pipe-pane inside container writes here

/mnt/gitdata/<org-repo>/                  /mnt/gitdata/<org-repo>/ (rw, same path)
/mnt/gitdata/amux/                            /mnt/gitdata/amux/          (ro)
  └── amux CLI                                  /usr/local/bin/amux → this
```

**Same path both sides is deliberate.** No path translation in prompts, git configs, or session logs. Whatever the host sees, the container sees.

## Session env file (`~/.amux/sessions/<name>.env`)

The switches that matter for isolation:

| Key | Values | Effect |
|---|---|---|
| `CC_RUNTIME` | unset (default) / `docker:<org>` | Runtime target. Unset = host. Docker = spawn tmux via `docker exec` into that org's container. |
| `CC_CLAUDE_AUTH_SHARED` | `"1"` (default) / `"0"` | Docker-only. `1` = share the container's `/home/amux/.claude/`. `0` = get own `/homes/<session>/.claude/` via `-e HOME` override. |
| `CC_DIR` | absolute path | Working dir. For docker sessions this MUST be a path that resolves inside the container via mounts. |
| `CC_PROVIDER` | `claude` / `codex` / `gemini` | Which CLI runs. `codex` sessions need the Codex CLI in the image (already installed). |
| `CC_FLAGS` | e.g. `--model claude-fable-5` | Passed to the provider CLI. |
| `CC_ORG` | e.g. `RTG` | Informational grouping. Independent of `CC_RUNTIME`. |
| `CC_ARCHIVED` | `"1"` = archived | Blocks start until `POST /api/sessions/<name>/wake`. |

## Auth model in one paragraph

Every org container mounts `~/.amux/orgs/<org>/home/` at `/home/amux/`, and the container image sets the amux user's home to `/home/amux/`. Every tmux session in the container inherits that HOME by default, so every session's `~/.claude/` (OAuth token, `.claude.json` project trust, `projects/*.jsonl` history) points to the same shared dir. **One `/login` per container covers all sessions in it.** If Jeremy wants a specific session on a different Claude account, set `CC_CLAUDE_AUTH_SHARED="0"` in that session's env — spawn adds `-e HOME=/homes/<session>` overriding the container default, giving that one session its own `.claude/` dir at `~/.amux/homes/<session>/` on host.

**Consequence for rate limits:** hitting a Claude account's usage limit stops every session in that container together, but no other container is affected. The whole point of the per-container split is that RTG hitting its ceiling doesn't take iSchedule / EmberCRM / ShareScore / CD-* work down.

## Shared credential files (2026-07-10)

`~/.amux/orgs/<org>/home/.claude/.credentials.json` used to be **per-container** — every org container had its own file, created by that container's own `/login`. The theory: refresh-token rotation would happen inside the container that used the token, and the file would stay valid.

**The theory was wrong.** Anthropic's OAuth flow DOES rotate the refresh token on every access-token refresh. When any session (including host `amux-helper`) with the same Anthropic account refreshes its access token, the old refresh token is invalidated — every OTHER container holding a stale copy of that refresh token is now dead. This bit us as a **wipe cascade** on 2026-07-10: 10 CD-* containers were all logged in as `jeremy@nwddi.com`; the moment `amux-helper` (also NWDDI) refreshed, all 10 containers were locked out simultaneously.

**Fix — shared bind-mounted credential files, per Anthropic account:**

```
/home/jwesley/.amux/shared-creds/
  ├── nwddi.credentials.json      (shared by all CD-* containers — jeremy@nwddi.com)
  └── personal.credentials.json   (shared by all Gmail-side containers — jeremywesley@gmail.com)
```

Every org container mounts the appropriate file into its home:

```yaml
# In ~/.amux/orgs/<org>.yml:
mounts:
  - source: /home/jwesley/.amux/shared-creds/nwddi.credentials.json   # or personal.credentials.json
    target: /home/amux/.claude/.credentials.json
    mode: rw
```

**Which file per org (as of 2026-07-10):**
- **NWDDI (`jeremy@nwddi.com`) — shared `nwddi.credentials.json`:** All 10 CD-* containers.
- **Jeremy-personal (`jeremywesley@gmail.com`) — shared `personal.credentials.json`:** RTG, iSchedule, EmberCRM, ShareScore, Cypra, Personal, Scorpio.
- **Independent (this session's host cred, NOT shared):** `amux-helper` on host. Stays at `~/.claude/.credentials.json`; this is the operator's cred and mustn't be pinned by any container to preserve one working access path when things break.

Whichever container's claude refreshes first rotates the token pair once; the shared file gets the new pair; every other container reads the fresh pair on its next check. No wipe cascade.

**Failure mode still possible — reboot-startup race:** If all Gmail-side containers restart simultaneously and each fires an initial token refresh, one of them will race the others and briefly hold a stale copy in memory, which can wipe the shared file. Recovery: copy a still-valid credentials file from a container that hasn't had claude re-read it yet (e.g., Scorpio, if it wasn't restarted at the same time as the others). Long-term mitigation: stagger session waking after a fleet cutover.

## How to add a new session to an existing org

1. `~/.amux/sessions/<name>.env` — write it (or copy an existing one, edit `CC_DIR`, `CC_FLAGS`, `CC_ORG`)
2. Append `CC_RUNTIME="docker:<org>"` to it
3. Append `CC_FLAGS="--dangerously-skip-permissions"` (YOLO mode is the default — the whole point of container isolation is that agents can run freely)
4. Add the session name to the `sessions:` list in `~/.amux/orgs/<org>.yml`
5. If the org's container is currently running, **stop it** so the next wake rebuilds with the new per-session home mount: `docker rm -f amux-org-<org>` (destroys nothing important; it's tini+tail). Next wake of any session in that org re-creates it with the updated mount set.
6. If you want conversation-history continuity, copy the relevant `~/.claude/projects/<slug>/*.jsonl` into `~/.amux/orgs/<org>/home/.claude/projects/<slug>/` before waking. See [Conversation-History-Locations](Conversation-History-Locations.md) for the encoding rules.

## How to add a new org

1. Write `~/.amux/orgs/<name>.yml`. Use the checklist below — every entry protects against a specific defect we've hit before, so **do not skip any mount** unless you have a documented reason:

   ```yaml
   # ~/.amux/orgs/<name>.yml — new org checklist (2026-07-10)
   name: <NewOrg>
   image: amux-agent-base:latest

   sessions:
     - <SessionName>

   mounts:
     # (1) Working repo — the code the agents actually edit. Same path both sides.
     - source: /mnt/gitdata/<repo>
       target: /mnt/gitdata/<repo>
       mode: rw

     # (2) amux repo read-only — makes the `amux` CLI shim at /usr/local/bin/amux
     # resolvable and lets agents read wiki/CLAUDE.md.
     - source: /mnt/gitdata/amux
       target: /mnt/gitdata/amux
       mode: ro

     # (3) SHARED credential file — pick the account this org belongs to.
     # See "Shared credential files" section for which file per org.
     # WHY: per-container creds hit a wipe cascade when Anthropic rotates
     # refresh tokens (2026-07-10 incident).
     - source: /home/jwesley/.amux/shared-creds/personal.credentials.json  # or nwddi.credentials.json
       target: /home/amux/.claude/.credentials.json
       mode: rw

     # (4) Thread attachments (uploads). Agents receive @-mentions like
     # @/home/jwesley/.amux/uploads/<uid>-<file>; without this bind mount the
     # container's Read tool says "file not found". Same-path both sides so
     # @-mention paths resolve verbatim. Read-only — containers don't upload.
     # See sub-shape F in reference-amux-container-host-state-family.
     - source: /home/jwesley/.amux/uploads
       target: /home/jwesley/.amux/uploads
       mode: ro

     # (5) Per-org SSH deploy key + gitconfig. Every existing CD-* / Big-4
     # org has these; new orgs should too if the agent will do any git work
     # (clone client repos, commit + push to per-client repos, ssh into
     # provisioned VMs). The SSH content is COPIED (not symlinked) from any
     # existing sibling org so a compromise on one org can't reach another's
     # key file. All CD-* orgs happen to share the same deploy_key CONTENT
     # (jwesley@btrcc01 ed25519) already authorized on the NWDDI org's
     # GitHub repos + per-client hosts — new CD-* orgs reuse it. Big-4 orgs
     # each have their own scoped key. Playbook step (below): amux-helper
     # `mkdir -p ~/.amux/orgs/<name>/secrets/ssh`, `cp` `deploy_key` +
     # `deploy_key.pub` + `config` + empty `known_hosts` from a sibling
     # org's secrets dir, `cp` `gitconfig` too, chmod 700/600/644 per file.
     - source: ~/.amux/orgs/<name>/secrets/ssh
       target: /home/amux/.ssh
       mode: rw
     - source: ~/.amux/orgs/<name>/secrets/gitconfig
       target: /home/amux/.gitconfig
       mode: ro

     # (6) Shared agent-skills library (Zoho REST API playbooks, etc.).
     # Read-only — skills are curated in github.com/j3rm/agent-skills and
     # mounted so every agent can consult the same procedures without
     # duplicating them into each org tree. Added fleet-wide 2026-07-13
     # per Jeremy after discovering CD-* containers had no way to reach
     # the shared skills (agents were operating from CLAUDE.md-encoded
     # procedures alone).
     - source: /mnt/gitdata/agent-skills
       target: /mnt/gitdata/agent-skills
       mode: ro

   readonly_cross_mounts: []
   env:
     # Per-org MCP credentials (Mixpeek, GDrive, etc.) — usually empty at
     # first rollout; fill in as needed.
     MIXPEEK_API_KEY: ""
   ```

2. Copy it to the corresponding `.agents/` dir in a backup git repo:
   - Big-4 (RTG/iSchedule/EmberCRM/ShareScore) → `<org-tree>/.agents/org-spec.yml` → `github.com/j3rm/amux-agents-<org>`
   - CD-<client> / misc → `/mnt/gitdata/amux-agents-mono/<name>/org-spec.yml` → `github.com/j3rm/amux-agents-mono`
3. Commit + push the backup
4. Set `CC_RUNTIME="docker:<name>"` on each of the sessions listed in the spec's `sessions:`
5. **Seed the container home from a sibling org — for shared-cred orgs only.** The shared `.credentials.json` mount alone is NOT enough; Claude Code also needs `.claude.json` (config file that says "you're logged in as this account, here's your trust map"). If missing, the session lands at the OAuth login screen even though tokens are present (2026-07-13: CD-CPAP hit this on first wake). Fix:
   ```bash
   SRC=~/.amux/orgs/<sibling-org>/home        # e.g. CD-Wattco for a new CD-*, EmberCRM for a new Big-4
   DST=~/.amux/orgs/<name>/home
   cp -a "$SRC/.claude.json"           "$DST/.claude.json"
   cp -a "$SRC/.claude/.mcp.json"      "$DST/.claude/.mcp.json"      # if the sibling has one
   cp -a "$SRC/.claude/settings.json"  "$DST/.claude/settings.json"  # if the sibling has one
   ```
   Skip this step for a first-of-a-kind org that will do a fresh `/login` — those need to authenticate to populate `.claude.json` and the shared cred file organically.
6. Wake one session in the org first (serial — avoids `ensure_org_container` race). Verify the container comes up. Then wake the rest.
7. Next section for the shared amux-agent-base image behaviors your new container inherits from tonight's changes.

That's it — no code change. `ensure_org_container(name)` reads the spec on demand.

## What the amux-agent-base image gives you (Dockerfile behaviors, 2026-07-10)

Every container built from `amux-agent-base:latest` inherits three defaults that were added after live-incident debugging. **Do not remove these from the Dockerfile without reading the WHY first — each one exists because it burned us.**

1. **`/usr/local/lib/node_modules` and `/usr/local/bin` are chowned to `amux:amux`.** Claude Code and Codex both auto-update themselves via `npm install -g` on startup. The base image runs `npm install -g` as root, so those dirs are root-owned by default. When the amux user (uid 1000) tries to update, it EACCES and — critically — Claude Code **exits to bash on the failure** instead of just warning. Half the fleet crash-looped on 2026-07-10 morning until we chowned. Blast radius: an agent could `npm install -g` a malicious replacement into its own container image, but every agent already runs `--dangerously-skip-permissions` so this doesn't widen the trust model.

2. **`CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1` is set globally.** Amux drives every session through `tmux capture-pane` (for dashboard peek, mobile web UI, SMS/thread reply detection). When Claude Code enters the terminal's alternate-screen buffer (its default), `capture-pane` returns an empty screen with just the input prompt — peek text is garbled, SMS reply detection breaks, `/tui default` has to be typed by hand every restart. The env var forces native-scrollback mode so `capture-pane` sees the full conversation. Set at ENV level so every claude spawn in every session in every container inherits it — no per-session opt-in, no drift when `/compact` resets config.

3. **`ENV TMUX_TMPDIR=/run/tmux`.** Keeps container's tmux daemon distinct from host's under sloppy mount configs (in case a spec ever bind-mounts `/tmp`).

## Fleet-wide container recreation (rollout procedure)

When you change the Dockerfile — new base package, new ENV var, new chown — running containers **do not** pick it up until they're recreated. `docker restart` only restarts the tini process; it doesn't re-pull the image. Full procedure:

```bash
# 1. Verify the Dockerfile change is valid.
python3 -c "import ast; ast.parse(open('/mnt/gitdata/amux/amux-server.py').read())"  # sanity

# 2. Rebuild the image. Tag stays `amux-agent-base:latest`.
cd /mnt/gitdata/amux
docker build -t amux-agent-base:latest agent-container/
# Verify the change is in the new image:
docker run --rm amux-agent-base:latest sh -c '<check-command>'

# 3. Snapshot non-archived container sessions BEFORE stopping.
# (Skips host-mode sessions like amux-helper — they don't need swapping.)
curl -sk https://localhost:8822/api/sessions | python3 -c "
import json,sys
d = json.load(sys.stdin)
for s in d:
    if s.get('archived'): continue
    if not s.get('runtime','').startswith('docker:'): continue
    print(s['name'])
" > /tmp/cutover-sessions.txt

# 4. Stop every session in parallel (fast — /stop is async 202).
cat /tmp/cutover-sessions.txt | xargs -I {} -P 10 -n 1 \
  curl -sk -X POST -o /dev/null "https://localhost:8822/api/sessions/{}/stop"
sleep 20   # let /stop drain

# 5. Force-remove every org container. The writable layer is discarded here —
# this reclaims the disk that auto-update bloat consumed.
for c in $(docker ps --format '{{.Names}}' | grep '^amux-org-'); do
  docker rm -f "$c"
done

# 6. Wake ONE session per org first (serial), so ensure_org_container runs
# cleanly before the rest race it. Then parallel-wake the remainder.
# (Use the by-org first-name selector from the amux-helper session's turn on
# 2026-07-10 for exact code.)

# 7. Verify fleet — sample peek per org:
for s in RTG-Research iSchedule-Main Ember-Research CD-WattcoAccMigration; do
  curl -sk "https://localhost:8822/api/sessions/$s/peek" | python3 -c "..."
done

# 8. Handle stragglers manually:
#    - Codex sessions may need `codex_session_id` cleared from their
#      <name>.meta.json (see "Codex session-id gotcha" below).
#    - Any session at the resume picker: send `Enter` via /keys.
#    - Any session at a Codex update prompt: Down Down Enter (Skip until next).
#    - Any session showing "Fullscreen feedback": Esc.
```

**Expected reclaim:** Immediately after the swap, each container's writable layer is ~7MB. Within a few minutes, it grows to ~500MB per container as Claude Code / Codex auto-update and rewrite `/usr/local/lib/node_modules`. Net: fleet-wide the swap trades ~11GB (accumulated cruft) for ~8GB (fresh package trees). **Budget for this: keep at least 20GB free on the root LV before starting a cutover, and monitor `df -h /` afterward.**

**When you MUST run a cutover:**
- Dockerfile changed (image needs to rebuild + containers need to see it)
- Writable-layer bloat is eating disk (any container hits `>1GB` in `docker ps --size`)
- A shared bind mount was added/changed in an org spec (container needs `docker rm -f` for the new mount to take effect on wake — an existing container doesn't dynamically remount)

**When you MUST NOT run a cutover:**
- During active agent work — every claude/codex process inside the containers dies. Bind-mounted state (conversations, creds) survives, but any in-memory context is lost. Do it during quiet hours.
- Without confirming disk headroom — the cutover writes ~500MB per container as auto-update runs.

## Codex session-id gotcha (post-cutover)

`~/.amux/sessions/<name>.meta.json` for Codex sessions holds a `codex_session_id`. Amux uses it to `codex resume --session <id>` on wake. **When a container is recreated (fleet cutover), the codex session inside is gone; the meta's session ID is now stale, and codex prints `ERROR: No saved session found with ID <uuid>. Run "codex resume".` The session sits idle.**

Fix — clear the stale ID:

```bash
python3 -c "
import json
p = '/home/jwesley/.amux/sessions/<name>.meta.json'
d = json.load(open(p)); d.pop('codex_session_id', None)
json.dump(d, open(p, 'w'), indent=2)
"
curl -sk -X POST https://localhost:8822/api/sessions/<name>/stop
sleep 8
curl -sk -X POST https://localhost:8822/api/sessions/<name>/wake
```

Cleanest way to spot these after a cutover: peek every codex-provider session; any "No saved session found" needs this fix.

## How to give a container read-only access to another org's code

Springboard pattern (e.g., let an RTG agent reference EmberCRM's Angular code without granting write access):

Edit `~/.amux/orgs/RTG.yml`:
```yaml
readonly_cross_mounts:
  - source: /mnt/gitdata/EmberCRM/Ember_OPS_Web_AngularJS
    target: /mnt/gitdata/EmberCRM/Ember_OPS_Web_AngularJS
    mode: ro
```

Then `docker rm -f amux-org-RTG` so next wake picks up the new mount. Nothing else changes.

## What happens on first wake of a docker session (mental model)

```
POST /api/sessions/RTG-Research/wake
  → clears CC_ARCHIVED
  → start_session("RTG-Research")
    → _session_runtime → "docker:RTG"
    → ensure_org_container("RTG")
      → loads ~/.amux/orgs/RTG.yml
      → creates ~/.amux/orgs/RTG/home/ if missing
      → creates ~/.amux/homes/RTG-Research/ (and 12 others) if missing
      → docker run -d --name amux-org-RTG
         --add-host host.docker.internal:host-gateway
         --restart unless-stopped
         -v ~/.amux/orgs/RTG/home:/home/amux:rw       ← shared login
         -v ~/.amux/homes/RTG-Research:/homes/RTG-Research:rw
         -v ~/.amux/homes/RTG-Dispatch:/homes/RTG-Dispatch:rw
         ... (per-session homes)
         -v /mnt/gitdata/RemoteTechGroup:/mnt/gitdata/RemoteTechGroup:rw
         -v /mnt/gitdata/RTG-AccountingMigration:/mnt/gitdata/RTG-AccountingMigration:rw
         -v /mnt/gitdata/ACT_CRM:/mnt/gitdata/ACT_CRM:rw
         -v /mnt/gitdata/amux:/mnt/gitdata/amux:ro
         -v ~/.amux/logs:/logs:rw
         amux-agent-base:latest
    → _auto_trust_dir writes ~/.amux/orgs/RTG/home/.claude.json
       marking work_dir as trusted
    → docker exec amux-org-RTG tmux new-session -d
       -s amux-RTG-Research
       -c /mnt/gitdata/RemoteTechGroup/.agents/RTG-Research
       -e TMUX_SESSION_NAME=RTG-Research
       -e AMUX_SESSION=RTG-Research
       -e AMUX_URL=https://host.docker.internal:8822
       bash
       (no -e HOME override — inherits /home/amux from image)
    → tmux send-keys "claude --model claude-fable-5 --name RTG-Research"
    → Claude Code starts, sees empty ~/.claude/, prompts /login
    → Jeremy /logs in as JEREMY (this is RTG)
    → OAuth token → ~/.amux/orgs/RTG/home/.claude/.credentials.json
    → From now on: every wake of any RTG session finds the token, no prompt
```

## Debugging cheatsheet

**Is a container running?**
```bash
docker ps --filter name=amux-org- --format '{{.Names}} {{.Status}}'
```

**What's inside a container's tmux?**
```bash
docker exec amux-org-RTG tmux list-sessions
```

**Where did a docker session's Claude Code state actually go?**
```bash
ls -la ~/.amux/orgs/RTG/home/.claude/
cat ~/.amux/orgs/RTG/home/.claude.json | jq .projects   # trust entries
```

**Peek inside a session as a shell:**
```bash
docker exec -it amux-org-RTG bash
# once inside:
echo $HOME                                  # /home/amux (shared) or /homes/<session>
ls ~/.claude/                               # what auth state Claude sees
amux --help                                 # verify /mnt mount + PATH symlink
```

**Force a fresh container rebuild for a org (picks up spec changes):**
```bash
# Session must be archived/stopped first — this rips the container out.
docker rm -f amux-org-RTG
# Next wake will rebuild from the current .yml
```

**Verify a session's runtime routing:**
```bash
grep '^CC_RUNTIME=' ~/.amux/sessions/RTG-Research.env
# CC_RUNTIME="docker:RTG"
```

**Which sessions belong to which container (canonical view):**
```bash
for f in ~/.amux/sessions/*.env; do
  rt=$(grep '^CC_RUNTIME=' "$f" | cut -d= -f2- | tr -d '"')
  [ -n "$rt" ] && echo "$rt $(basename "$f" .env)"
done | sort | uniq -c
```

**Where's the log?**
- Host absolute: `~/.amux/logs/<name>.log` (up to 10MB rolling)
- Container-visible: `/logs/<name>.log` (same file, bind mount)
- pipe-pane inside container writes to the container path; host reads the same file directly.

**"Read your log" prompt** (auto-sent on wake) resolves via `_log_path_in_runtime` — host sessions see host absolute path, docker sessions see `/logs/<name>.log`. Both work.

## Where secrets go (or don't)

**Right now, containers have NO secrets mounted by default.** The current specs only mount working repos + amux repo (ro) + logs. Meaning: inside a docker container, `~/.ssh/` is empty, `~/.aws/credentials` doesn't exist, `~/.zoho/<client>/` isn't there. Sessions will fail on git-over-SSH, AWS CLI calls, or Zoho token reads until Phase 8 (the secrets partition) lands.

**Phase 8 plan** (not yet implemented): per-org secret dirs at `/opt/amux/secrets/<org>/` (or an equivalent under `~/.amux/secrets/<org>/` since AMUX runs as jwesley), bind-mounted read-only into each container's `/home/amux/.ssh/`, `/home/amux/.zoho/`, etc. Per-product SSH keys/Zoho tokens/etc. means an RTG agent physically can't read iSchedule's secrets.

**For the transition:** the current `/mnt/gitdata/amux` mount is ro, so agents can still read the amux repo. If a specific org needs a secret before Phase 8, add a per-org `mounts:` entry temporarily.

## The critical CC_RUNTIME → runtime → daemon path

Every session-scoped tmux call in `amux-server.py` goes through `_tmux_cmd(session, *args)`:

```python
def _tmux_prefix(session):
    rt = _session_runtime(session)   # reads CC_RUNTIME from session env
    if rt == "host":
        return ["tmux"]
    if rt.startswith("docker:"):
        org = rt.split(":", 1)[1]
        return ["docker", "exec", f"amux-org-{product}", "tmux"]
    return ["tmux"]  # unknown → degrade to host
```

Same call, different daemon at execution time. No caching — every call re-reads the env file. Changing `CC_RUNTIME` in an env file takes effect on the next tmux operation. This is the entire hinge of the container switch — the ~80 routed call sites (`_tmux_cmd(name, ...)`) route based on this.

## Enumeration union (dashboard would otherwise lie)

`_tmux_info_map()` unions host tmux + every running org container's tmux via `_running_org_containers()` + `docker exec ... tmux list-panes -a`. This drives:
- `/api/sessions` (dashboard shows correct `running: true` for docker sessions)
- `_snapshot_all_sessions_inner` (monitoring loop covers docker sessions)
- Rate-limit / auto-restart / hibernate scans

Without this, everything about a docker session looks "not running" to the server even when it's live.

## Backup + recovery topology

| What | Where the source-of-truth lives | Offsite backup |
|---|---|---|
| amux-server code | `/mnt/gitdata/amux/amux-server.py` (single file) | `github.com/j3rm/amux` `jwesley-main` |
| Container image spec | `/mnt/gitdata/amux/agent-container/Dockerfile` | same repo |
| Org specs | `~/.amux/orgs/*.yml` (14 files) | Backups in `github.com/j3rm/amux-agents-<org>` at `<org-tree>/.agents/org-spec.yml` (RTG/iSchedule/EmberCRM/ShareScore) or in `github.com/j3rm/amux-agents-mono` under `<org>/org-spec.yml` (CD-*) |
| Session env files | `~/.amux/sessions/*.env` | not backed up offsite — flatten into a git repo if that concerns you |
| Agent role configs (`CLAUDE.md`, `AGENTS.md`) | Product-repo `.agents/<agent>/CLAUDE.md` | `amux-agents-<org>` (Big-4) or `amux-agents-mono` (rest) — all pushed 2026-07-08 |
| Per-container `~/.claude/` (auth + JSONLs) | `~/.amux/orgs/<org>/home/.claude/` | **NOT backed up.** OAuth tokens shouldn't sync anyway. Conversation JSONLs would fit in a snapshot to R2 or similar. |
| Per-session logs | `~/.amux/logs/<name>.log` | not backed up — 10 MB rolling |

## Agent orientation: how they know they're in a container

Zero per-agent `CLAUDE.md` edits needed. The server auto-injects a container-context preamble into every docker-mode session's composed `MEMORY.md` at spawn time (`_container_context_preamble` in `amux-server.py`, prepended by `_write_claude_memory`).

The preamble is regenerated on every `_ensure_memory` call (i.e. every session start), so any change to `~/.amux/orgs/<org>.yml` — new sibling session added, new mount, new cross-mount — is picked up on the next wake without touching anything else.

What each docker session sees at the top of its `MEMORY.md`:
- Its container name (`amux-org-<X>`)
- The list of sibling sessions sharing its `~/.claude/` (so agents know their Claude account is shared and can be mindful of tokens)
- The exact mounted paths with modes — establishes "nothing else on the host is visible"
- Where to hit the AMUX API (`host.docker.internal:8822`) and that the `amux` CLI + board/threads/channels are unchanged
- Instruction: if you need a cross-product read-only view, ask Jeremy to add to `readonly_cross_mounts:` — don't work around it

Host-mode sessions get an empty string prepended (no-op). Their behaviour is unchanged.

Commit: `bdfb43c feat(isolation): container-context preamble in composed memory`.

## Related memory

- [[amux-isolation-plan]] — decision quotes from Jeremy, phase-by-phase commits, list of known limitations at first wake
- [[session-kill-loop]] — historical kill-loop root causes; relevant if a docker session starts thrashing
- [[systemd-watchdog]] — amux-server itself is under systemd; if it crashes, its own auto-restart brings it back; container `--restart unless-stopped` handles the container side
- [[reference-amux-intersession-api]] — the board/threads/notes API surface that container sessions reach via `AMUX_URL=https://host.docker.internal:8822`
