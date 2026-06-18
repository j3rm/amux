# Remote-agent doorbell system

**Contributed by RTG-VS2017, 2026-06-18** (tested on Windows 10 + Claude Code
CLI). Generalized here as the reusable pattern for **any** remote amux agent
(RTG-VS2017, LYNQ-Mac, and future ones).

## The problem

Remote agents (a Windows build box, a Mac with USB access, etc.) run Claude
Code **outside** amux-managed tmux. So the server's normal doorbell —
`tmux send-keys` — can't reach them. Their only options were:
- **Poll from inside Claude** — burns tokens on a loop that's idle 99% of the
  time, and stops the moment the agent goes idle.
- **Wait for a human to prompt them** — which is exactly how work gets dropped.

This system gives a remote agent a real doorbell at **zero Claude-token cost**:
a tiny background poller watches the board and *injects* a wake message into the
running Claude Code terminal when work arrives — the Windows/Mac equivalent of
`tmux send-keys`.

## Architecture

```
amux board
   │  curl every ~60s  (background shell script — NO Claude tokens)
   ▼
poll-board.sh ──new item for me?──▶ send-to-claude.ps1
                                        │  SendKeys → types into the terminal
                                        ▼
                                 Claude Code terminal  (agent wakes, works)
```

### Two components

**1. `poll-board.sh` — background board poller (bash; Git-Bash/WSL on Windows)**
- Runs detached (`nohup bash poll-board.sh &`), independent of Claude — costs
  no tokens (just `curl` + a little `python`/`jq` filtering).
- Every ~60s, fetches the board and filters for items assigned to this session
  (`$AMUX_SESSION`).
- Optional business-hours gate (timezone-aware, M–F) so it's quiet off-hours.
- Safeguards:
  - **`.busy` lock** — while the agent is mid-task it writes `.busy`; the poller
    then *queues* alerts instead of injecting and corrupting an in-progress
    prompt. When `.busy` is removed, the next cycle delivers the queued alert.
  - **`.notified-items`** — tracks item IDs already rung so it never double-rings.
  - **PID file** — clean start/stop.

**2. `send-to-claude.ps1` — Windows terminal injector (PowerShell)**
- Finds the Claude Code terminal window by title, foregrounds it, and types a
  message via `System.Windows.Forms.SendKeys`.
- Escapes all SendKeys metacharacters (`+ ^ % ~ { } [ ] ( )`).
- `-Text "msg"` or `-File "path"` (for long messages).
- (On macOS the equivalent injector would use AppleScript `keystroke`; the
  bash poller is unchanged.)

## Setting it up for a new remote agent

1. Create the agent's working dir (e.g. `B:\<Agent>-remote\`).
2. Put `remote.env` there with `AMUX_URL`, `AMUX_TOKEN`, `AMUX_SESSION`.
   **Never commit `remote.env` or embed the token anywhere else** — chmod it
   600; it grants full amux control.
3. Copy `poll-board.sh` and `send-to-claude.ps1` into the dir.
4. In `poll-board.sh`: set the session filter to `$AMUX_SESSION`; adjust
   business hours/timezone/poll interval.
5. In `send-to-claude.ps1`: set the window-title match pattern for this agent's
   terminal.
6. In the agent's `CLAUDE.md`, add:
   - **Startup:** "On every context load, start the background poller if not
     already running, then check `board-alerts.json` for waiting work."
   - **Busy protocol:** `echo "$(date -Iseconds) ITEM-ID" > .busy` before
     starting a task; `rm -f .busy` after reporting results.
7. Start Claude Code in a terminal, then start the poller.

## Per-agent customization

| Setting | Where | Change to |
|---|---|---|
| Session name | `poll-board.sh` filter | match `$AMUX_SESSION` |
| Business hours | `poll-board.sh is_business_hours()` | timezone, hours, days |
| Window-title match | `send-to-claude.ps1` | agent's terminal title |
| Poll interval | `poll-board.sh POLL_INTERVAL` | default 60s |

## Runtime files (auto-created in the agent dir)

| File | Purpose |
|---|---|
| `.busy` | agent is working → queue alerts instead of injecting |
| `.notified-items` | item IDs already rung (no double-ring) |
| `.queued-alert` | alert waiting for the agent to free up |
| `board-alerts.json` | latest board snapshot |
| `poll-board.{log,pid}` | poller activity log / process id |

## Status / where the scripts live

The full `poll-board.sh` and `send-to-claude.ps1` source currently live in the
`RTG-VS2017-remote` directory on the Windows build machine. They are **not yet
in this repo** — if we want them version-controlled, have RTG-VS2017 send the
source and drop them under a `remote-agent-kit/` folder (scrubbed of any
`remote.env`/token). This page documents the design RTG-VS2017 contributed.
