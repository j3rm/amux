# Codegraph MCP — per-org code graph via SSH

Each amux org (RTG, EmberCRM, iSchedule, ShareScore) has an isolated
Neo4j-backed code graph on a shared server. Access is over SSH to
`192.168.72.85` (`DAL-prod-codegraph-db-01`) using a per-org private
key. The MCP client is `ssh` itself; each key is restricted server-side
to that org's config, so cross-org queries are impossible even if a
container tried.

Deployed 2026-08-27 by Jeremy + amux-helper. Owner-of-record for server-
side setup: Scorpio (see Scorpio's session for the codegraph server
provisioning notes).

## Key mapping

| Org       | Key name on server                  | Host path (this box)                                      | Container path         |
|-----------|-------------------------------------|-----------------------------------------------------------|------------------------|
| RTG       | `/etc/codegraph/mcp-keys/mcp_rtg`   | `~/.amux/orgs/RTG/secrets/ssh/codegraph_key`              | `/home/amux/.ssh/codegraph_key` |
| EmberCRM  | `/etc/codegraph/mcp-keys/mcp_ember` | `~/.amux/orgs/EmberCRM/secrets/ssh/codegraph_key`         | `/home/amux/.ssh/codegraph_key` |
| iSchedule | `/etc/codegraph/mcp-keys/mcp_ischedule` | `~/.amux/orgs/iSchedule/secrets/ssh/codegraph_key`        | `/home/amux/.ssh/codegraph_key` |
| ShareScore/WhatNumber | `/etc/codegraph/mcp-keys/mcp_sswn` | `~/.amux/orgs/ShareScore/secrets/ssh/codegraph_key` | `/home/amux/.ssh/codegraph_key` |

All keys are OpenSSH format, 419–432 bytes, chmod 600, owner
`jwesley:jwesley` on host (maps to container user `amux`). Server-side,
each key is bound to a single `mcp-homes/<org>/` config so it can only
start the MCP server for that org.

The host jump key (`/etc/claude-deploy/keys/deploy_rsa`) is used ONLY
for the initial pull of the per-org keys from the server. Containers
do NOT get the deploy_rsa key — they use their own per-org key.

## MCP config shape

Merged into each org's `~/.mcp.json` AND `~/.claude/.mcp.json` (both
present with identical content; the paths on host are
`~/.amux/orgs/<ORG>/home/.mcp.json` and
`~/.amux/orgs/<ORG>/home/.claude/.mcp.json`):

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "ssh",
      "args": [
        "-i", "/home/amux/.ssh/codegraph_key",
        "-o", "StrictHostKeyChecking=no",
        "deploy@192.168.72.85"
      ]
    }
  }
}
```

No env vars, no `mcp start` argument, no client-side project selector —
the server picks the config to run based on which key authenticated.

## PreToolUse / PostToolUse hooks (Jeremy 2026-08-27)

To enforce the "query graph before grep" rule, each org has a pair of
hooks under `.claude/hooks/` and a config in `.claude/settings.json`:

- **`check-codegraph.sh`** (PreToolUse, matcher `Grep|Glob`) — blocks
  with exit 2 when the query looks like a structural symbol lookup
  (`^[A-Za-z_][A-Za-z0-9_]*$` OR contains `class `, `def `, `function `,
  `=>`, `interface `). Plain-text searches (URLs, prose, config values)
  pass through. Once the session has consulted codegraph, the flag
  `/tmp/claude-codegraph-flags/<session_id>` unblocks subsequent greps.
- **`mark-codegraph-used.sh`** (PostToolUse, matcher `mcp__codegraph__.*`)
  — drops the per-session flag file after any codegraph MCP tool call.

**Matcher gotcha:** Claude Code emits MCP tool names as
`mcp__<server-name>__<tool-name>`. `<server-name>` is the key under
`mcpServers` in `.mcp.json`. Our registration uses `codegraph`, so the
matcher is `mcp__codegraph__.*`. If a future MCP registration uses a
different server-name (e.g. `code-graph-context`), the matcher must be
updated in each org's `.claude/settings.json` — otherwise the flag
never lands and Grep stays blocked forever.

**Requires `jq`** in each container (verified 2026-08-27: all 4 have
jq-1.7 at `/usr/bin/jq`).

## Agent instructions

Each org's project `CLAUDE.md` has a `## Codebase Navigation — MANDATORY`
section (Jeremy 2026-08-27) directing agents to query the graph before
Grep/Glob for any "where is X" or "what calls X" question, and to run
`find_callers` before modifying any function or class.

Documented MCP tool names (from Jeremy's mandatory section):
- `find_definition` — where is a function/class/method defined?
- `find_callers` — who calls this?
- `find_dependencies` — what does this depend on?
- `trace_relationships` — how does data flow between components?

If the actual MCP client exposes different tool names, the agent should
use what the client shows and file a board item so this doc gets
corrected. Do NOT invent tool names.

Freshness: the graph is periodically re-indexed. If findings look stale,
the agent should call it out in their response and file a board item to
Jeremy for a re-index — do NOT try to re-index from a container.

## Redeploy from scratch (recovery playbook)

If a container's key is lost or corrupted:

```bash
# 1. Re-pull the per-org key from the codegraph server via the host jump key.
KEY_NAME=rtg  # or ember, ischedule, sswn
ORG_DIR=RTG   # or EmberCRM, iSchedule, ShareScore
ssh -i /etc/claude-deploy/keys/deploy_rsa \
    -o StrictHostKeyChecking=no \
    deploy@192.168.72.85 \
    "sudo cat /etc/codegraph/mcp-keys/mcp_$KEY_NAME" \
  > ~/.amux/orgs/$ORG_DIR/secrets/ssh/codegraph_key
chmod 600 ~/.amux/orgs/$ORG_DIR/secrets/ssh/codegraph_key
# 2. The mount is live — no docker restart needed. Verify from inside:
docker exec amux-org-$ORG_DIR ls -la /home/amux/.ssh/codegraph_key
```

If MCP config is lost (a `.mcp.json` was overwritten):

```bash
# Re-merge codegraph into the org's .mcp.json using Python (never edit
# by hand — you'll clobber other MCP servers).
python3 <<PYEOF
import json
for f in [
    f"/home/jwesley/.amux/orgs/$ORG_DIR/home/.mcp.json",
    f"/home/jwesley/.amux/orgs/$ORG_DIR/home/.claude/.mcp.json",
]:
    d = json.load(open(f))
    d.setdefault("mcpServers", {})["codegraph"] = {
        "command": "ssh",
        "args": ["-i", "/home/amux/.ssh/codegraph_key",
                 "-o", "StrictHostKeyChecking=no",
                 "deploy@192.168.72.85"]
    }
    open(f, "w").write(json.dumps(d, indent=2) + "\n")
PYEOF
```

## Smoke test (from container)

Fastest end-to-end check that a container can actually reach codegraph
and the server-side config is bound to this org:

```bash
docker exec amux-org-RTG bash -c '
  ls -la /home/amux/.ssh/codegraph_key
  timeout 5 ssh -i /home/amux/.ssh/codegraph_key \
    -o StrictHostKeyChecking=no -o ConnectTimeout=3 \
    deploy@192.168.72.85 "echo IN_CONTAINER_OK; hostname" 2>&1 | head -3
'
```

Expected output (verified 2026-08-27):
```
Starting CodeGraphContext Server...
Loaded configuration from: /etc/codegraph/mcp-homes/rtg/.codegraphcontext/.env
```

The `mcp-homes/<org>/` path in the second line confirms server-side
isolation is intact — if that path shows a different org, the wrong
key landed in the container.

## Adding a new org

1. **Server-side (Scorpio):** create `/etc/codegraph/mcp-keys/mcp_<neworg>`
   restricted to `/etc/codegraph/mcp-homes/<neworg>/` — mirror the
   existing per-org setup.
2. **This box:** pull the key using the recovery playbook above, into
   the new org's `secrets/ssh/codegraph_key`.
3. **MCP config:** merge the codegraph entry into the new org's
   `.mcp.json` files (recovery playbook).
4. **Agent instructions:** append the `## Codegraph — the project's
   code graph (MCP)` section to the new org's project `CLAUDE.md`
   (verbatim from any existing org — the section body is the same).
5. **Smoke test** from inside the new container as above.
6. **This doc:** add a row to the Key mapping table.

## Related

- Scorpio (agent) owns server-side codegraph provisioning + Neo4j.
- Instances of the same MCP pattern (SSH-as-transport) can be reused
  for any other per-org private service. Just swap the target host
  and the per-org key path.
- If a graph appears stale, agents should file a board item to Jeremy
  rather than trying to trigger a re-index themselves.
