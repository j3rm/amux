# AMUX per-product container isolation — ops reference

> The architecture is: **AMUX server runs on host, spawns tmux+claude INSIDE per-product containers.** Each product (RTG / iSchedule / EmberCRM / ShareScore / CD-*) is one long-lived Docker container. Every AMUX agent for that product is a tmux session inside that one container. `CC_RUNTIME=docker:<product>` on a session's env file is the switch that routes it. Sessions with no `CC_RUNTIME` keep running on host as before.

## Reading map — where to look first

- **This file** — how it works, where files live, how to extend/debug.
- **[[amux-isolation-plan]]** — decision history, phase-by-phase commit log, known limitations, decision quotes from Jeremy.
- **`fork/jwesley-main` on github.com/j3rm/amux** — source. Look at commits `feat(isolation):` (Phase 1a → 2g).
- **`~/.amux/products/*.yml`** — one file per product; edit these to change mounts/env/sessions.
- **agent-container/Dockerfile in the amux repo** — the image every product runs.
- **[[amux-isolation-plan]] "Ready-state before first wake"** — feature-by-feature what's wired up.

## Products at a glance

| Product | Container | Sessions | Working repos mounted |
|---|---|---|---|
| RTG | `amux-product-RTG` | 13 (Research/Dispatch + Audit-Codex + Audit-Opus48 + 8 workers + Artemis) | `/mnt/gitdata/RemoteTechGroup` rw, `/mnt/gitdata/RTG-AccountingMigration` rw, `/mnt/gitdata/ACT_CRM` rw |
| iSchedule | `amux-product-iSchedule` | 8 | `/mnt/gitdata/iSchedule` rw |
| EmberCRM | `amux-product-EmberCRM` | 13 | `/mnt/gitdata/EmberCRM` rw |
| ShareScore | `amux-product-ShareScore` | 2 | `/mnt/gitdata/ShareScore` rw |
| CD-AirCom | `amux-product-CD-AirCom` | 2 (Analytics + Catalyst) | `/mnt/gitdata/ClientData/AirCom` rw |
| CD-Classic-Pianos | `amux-product-CD-Classic-Pianos` | 1 | `/mnt/gitdata/ClientData/Classic Piano` rw |
| CD-In-DepthEvents | `amux-product-CD-In-DepthEvents` | 1 | `/mnt/gitdata/ClientData/In-DepthEvents` rw |
| CD-MyOwnerCircle | `amux-product-CD-MyOwnerCircle` | 1 | `/mnt/gitdata/ClientData/My Owner Circle` rw |
| CD-NPP | `amux-product-CD-NPP` | 1 | `/mnt/gitdata/ClientData/NPP` rw |
| CD-NRT | `amux-product-CD-NRT` | 1 | `/mnt/gitdata/ClientData/NRT` rw |
| CD-Shurloc | `amux-product-CD-Shurloc` | 1 | `/mnt/gitdata/ClientData/Shurloc` rw |
| CD-SurfPrep | `amux-product-CD-SurfPrep` | 1 | `/mnt/gitdata/ClientData/SurfPrep` rw |
| CD-Wattco | `amux-product-CD-Wattco` | 1 | `/mnt/gitdata/ClientData/Wattco` rw |
| CD-Wyoming | `amux-product-CD-Wyoming` | 1 | `/mnt/gitdata/ClientData/WyomingCorpServices` rw |

Every product container also gets `/mnt/gitdata/amux` **read-only** so the `amux` CLI (symlinked at `/usr/local/bin/amux → /mnt/gitdata/amux/amux`) resolves.

**Host-mode sessions (unchanged, run as jwesley with full host access):** `amux-helper`, `Cypra`, `Cypra-EmailAgent`, `Cypra-PAA`, `AMUX-Watchdog`, `Scorpio`, `RTG-VS2017` (remote), plus currently-unassigned: `LYNQ-GPS`, `N8N`, `SmarterTrackResearch`, `WordpressDesign`, `Vid-TM-Builder`, `Vid-TM-Orchestrator`, `Vid-TM-QC`.

## Where every file lives (host ↔ container)

```
HOST                                          CONTAINER (bind-mounted / env-set)
────────────────────────────────────────────────────────────────────────────────
~/.amux/products/<product>.yml                (read at spawn — never mounted)
~/.amux/products/<product>/home/              /home/amux/                (rw)
  ├── .claude/                                  ~/.claude/               ← shared login
  │     ├── .credentials.json                     └── OAuth token per product
  │     └── projects/<slug>/*.jsonl               └── conversation history
  └── .codex/config.toml                        ~/.codex/config.toml     ← codex trust

~/.amux/homes/<session>/                      /homes/<session>/          (rw)
  └── .claude/                                  used ONLY if CC_CLAUDE_AUTH_SHARED=0
                                                (per-session opt-out from shared login)

~/.amux/logs/<session>.log                    /logs/<session>.log        (rw, same inode)
                                                pipe-pane inside container writes here

/mnt/gitdata/<product-repo>/                  /mnt/gitdata/<product-repo>/ (rw, same path)
/mnt/gitdata/amux/                            /mnt/gitdata/amux/          (ro)
  └── amux CLI                                  /usr/local/bin/amux → this
```

**Same path both sides is deliberate.** No path translation in prompts, git configs, or session logs. Whatever the host sees, the container sees.

## Session env file (`~/.amux/sessions/<name>.env`)

The switches that matter for isolation:

| Key | Values | Effect |
|---|---|---|
| `CC_RUNTIME` | unset (default) / `docker:<product>` | Runtime target. Unset = host. Docker = spawn tmux via `docker exec` into that product's container. |
| `CC_CLAUDE_AUTH_SHARED` | `"1"` (default) / `"0"` | Docker-only. `1` = share the container's `/home/amux/.claude/`. `0` = get own `/homes/<session>/.claude/` via `-e HOME` override. |
| `CC_DIR` | absolute path | Working dir. For docker sessions this MUST be a path that resolves inside the container via mounts. |
| `CC_PROVIDER` | `claude` / `codex` / `gemini` | Which CLI runs. `codex` sessions need the Codex CLI in the image (already installed). |
| `CC_FLAGS` | e.g. `--model claude-fable-5` | Passed to the provider CLI. |
| `CC_ORG` | e.g. `RTG` | Informational grouping. Independent of `CC_RUNTIME`. |
| `CC_ARCHIVED` | `"1"` = archived | Blocks start until `POST /api/sessions/<name>/wake`. |

## Auth model in one paragraph

Every product container mounts `~/.amux/products/<product>/home/` at `/home/amux/`, and the container image sets the amux user's home to `/home/amux/`. Every tmux session in the container inherits that HOME by default, so every session's `~/.claude/` (OAuth token, `.claude.json` project trust, `projects/*.jsonl` history) points to the same shared dir. **One `/login` per container covers all sessions in it.** If Jeremy wants a specific session on a different Claude account, set `CC_CLAUDE_AUTH_SHARED="0"` in that session's env — spawn adds `-e HOME=/homes/<session>` overriding the container default, giving that one session its own `.claude/` dir at `~/.amux/homes/<session>/` on host.

**Consequence for rate limits:** hitting a Claude account's usage limit stops every session in that container together, but no other container is affected. The whole point of the per-container split is that RTG hitting its ceiling doesn't take iSchedule / EmberCRM / ShareScore / Christine-work down.

## How to add a new session to an existing product

1. `~/.amux/sessions/<name>.env` — write it (or copy an existing one, edit `CC_DIR`, `CC_FLAGS`, `CC_ORG`)
2. Append `CC_RUNTIME="docker:<product>"` to it
3. Add the session name to the `sessions:` list in `~/.amux/products/<product>.yml`
4. If the product's container is currently running, **stop it** so the next wake rebuilds with the new per-session home mount: `docker rm -f amux-product-<product>` (destroys nothing important; it's tini+tail). Next wake of any session in that product re-creates it with the updated mount set.
5. If you want conversation-history continuity, copy the relevant `~/.claude/projects/<slug>/*.jsonl` into `~/.amux/products/<product>/home/.claude/projects/<slug>/` before waking.

## How to add a new product

1. Write `~/.amux/products/<name>.yml` — see `agent-container/example-product.yml` for the schema
2. Copy it to the corresponding `.agents/` dir in a backup git repo:
   - RTG/iSchedule/EmberCRM/ShareScore → `<product-tree>/.agents/product-spec.yml` → `github.com/j3rm/amux-agents-<product>`
   - CD-<client> / misc → `/mnt/gitdata/amux-agents-mono/<name>/product-spec.yml` → `github.com/j3rm/amux-agents-mono`
3. Commit + push the backup
4. Set `CC_RUNTIME="docker:<name>"` on each of the sessions listed in the spec's `sessions:`

That's it — no code change. `ensure_product_container(name)` reads the spec on demand.

## How to give a container read-only access to another product's code

Springboard pattern (e.g., let an RTG agent reference EmberCRM's Angular code without granting write access):

Edit `~/.amux/products/RTG.yml`:
```yaml
readonly_cross_mounts:
  - source: /mnt/gitdata/EmberCRM/Ember_OPS_Web_AngularJS
    target: /mnt/gitdata/EmberCRM/Ember_OPS_Web_AngularJS
    mode: ro
```

Then `docker rm -f amux-product-RTG` so next wake picks up the new mount. Nothing else changes.

## What happens on first wake of a docker session (mental model)

```
POST /api/sessions/RTG-Research/wake
  → clears CC_ARCHIVED
  → start_session("RTG-Research")
    → _session_runtime → "docker:RTG"
    → ensure_product_container("RTG")
      → loads ~/.amux/products/RTG.yml
      → creates ~/.amux/products/RTG/home/ if missing
      → creates ~/.amux/homes/RTG-Research/ (and 12 others) if missing
      → docker run -d --name amux-product-RTG
         --add-host host.docker.internal:host-gateway
         --restart unless-stopped
         -v ~/.amux/products/RTG/home:/home/amux:rw       ← shared login
         -v ~/.amux/homes/RTG-Research:/homes/RTG-Research:rw
         -v ~/.amux/homes/RTG-Dispatch:/homes/RTG-Dispatch:rw
         ... (per-session homes)
         -v /mnt/gitdata/RemoteTechGroup:/mnt/gitdata/RemoteTechGroup:rw
         -v /mnt/gitdata/RTG-AccountingMigration:/mnt/gitdata/RTG-AccountingMigration:rw
         -v /mnt/gitdata/ACT_CRM:/mnt/gitdata/ACT_CRM:rw
         -v /mnt/gitdata/amux:/mnt/gitdata/amux:ro
         -v ~/.amux/logs:/logs:rw
         amux-agent-base:latest
    → _auto_trust_dir writes ~/.amux/products/RTG/home/.claude.json
       marking work_dir as trusted
    → docker exec amux-product-RTG tmux new-session -d
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
    → OAuth token → ~/.amux/products/RTG/home/.claude/.credentials.json
    → From now on: every wake of any RTG session finds the token, no prompt
```

## Debugging cheatsheet

**Is a container running?**
```bash
docker ps --filter name=amux-product- --format '{{.Names}} {{.Status}}'
```

**What's inside a container's tmux?**
```bash
docker exec amux-product-RTG tmux list-sessions
```

**Where did a docker session's Claude Code state actually go?**
```bash
ls -la ~/.amux/products/RTG/home/.claude/
cat ~/.amux/products/RTG/home/.claude.json | jq .projects   # trust entries
```

**Peek inside a session as a shell:**
```bash
docker exec -it amux-product-RTG bash
# once inside:
echo $HOME                                  # /home/amux (shared) or /homes/<session>
ls ~/.claude/                               # what auth state Claude sees
amux --help                                 # verify /mnt mount + PATH symlink
```

**Force a fresh container rebuild for a product (picks up spec changes):**
```bash
# Session must be archived/stopped first — this rips the container out.
docker rm -f amux-product-RTG
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

**Phase 8 plan** (not yet implemented): per-product secret dirs at `/opt/amux/secrets/<product>/` (or an equivalent under `~/.amux/secrets/<product>/` since AMUX runs as jwesley), bind-mounted read-only into each container's `/home/amux/.ssh/`, `/home/amux/.zoho/`, etc. Per-product SSH keys/Zoho tokens/etc. means an RTG agent physically can't read iSchedule's secrets.

**For the transition:** the current `/mnt/gitdata/amux` mount is ro, so agents can still read the amux repo. If a specific product needs a secret before Phase 8, add a per-product `mounts:` entry temporarily.

## The critical CC_RUNTIME → runtime → daemon path

Every session-scoped tmux call in `amux-server.py` goes through `_tmux_cmd(session, *args)`:

```python
def _tmux_prefix(session):
    rt = _session_runtime(session)   # reads CC_RUNTIME from session env
    if rt == "host":
        return ["tmux"]
    if rt.startswith("docker:"):
        product = rt.split(":", 1)[1]
        return ["docker", "exec", f"amux-product-{product}", "tmux"]
    return ["tmux"]  # unknown → degrade to host
```

Same call, different daemon at execution time. No caching — every call re-reads the env file. Changing `CC_RUNTIME` in an env file takes effect on the next tmux operation. This is the entire hinge of the container switch — the ~80 routed call sites (`_tmux_cmd(name, ...)`) route based on this.

## Enumeration union (dashboard would otherwise lie)

`_tmux_info_map()` unions host tmux + every running product container's tmux via `_running_product_containers()` + `docker exec ... tmux list-panes -a`. This drives:
- `/api/sessions` (dashboard shows correct `running: true` for docker sessions)
- `_snapshot_all_sessions_inner` (monitoring loop covers docker sessions)
- Rate-limit / auto-restart / hibernate scans

Without this, everything about a docker session looks "not running" to the server even when it's live.

## Backup + recovery topology

| What | Where the source-of-truth lives | Offsite backup |
|---|---|---|
| amux-server code | `/mnt/gitdata/amux/amux-server.py` (single file) | `github.com/j3rm/amux` `jwesley-main` |
| Container image spec | `/mnt/gitdata/amux/agent-container/Dockerfile` | same repo |
| Product specs | `~/.amux/products/*.yml` (14 files) | Backups in `github.com/j3rm/amux-agents-<product>` at `<product-tree>/.agents/product-spec.yml` (RTG/iSchedule/EmberCRM/ShareScore) or in `github.com/j3rm/amux-agents-mono` under `<product>/product-spec.yml` (CD-*) |
| Session env files | `~/.amux/sessions/*.env` | not backed up offsite — flatten into a git repo if that concerns you |
| Agent role configs (`CLAUDE.md`, `AGENTS.md`) | Product-repo `.agents/<agent>/CLAUDE.md` | `amux-agents-<product>` (Big-4) or `amux-agents-mono` (rest) — all pushed 2026-07-08 |
| Per-container `~/.claude/` (auth + JSONLs) | `~/.amux/products/<product>/home/.claude/` | **NOT backed up.** OAuth tokens shouldn't sync anyway. Conversation JSONLs would fit in a snapshot to R2 or similar. |
| Per-session logs | `~/.amux/logs/<name>.log` | not backed up — 10 MB rolling |

## Agent orientation: how they know they're in a container

Zero per-agent `CLAUDE.md` edits needed. The server auto-injects a container-context preamble into every docker-mode session's composed `MEMORY.md` at spawn time (`_container_context_preamble` in `amux-server.py`, prepended by `_write_claude_memory`).

The preamble is regenerated on every `_ensure_memory` call (i.e. every session start), so any change to `~/.amux/products/<product>.yml` — new sibling session added, new mount, new cross-mount — is picked up on the next wake without touching anything else.

What each docker session sees at the top of its `MEMORY.md`:
- Its container name (`amux-product-<X>`)
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
