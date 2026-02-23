# amux — Claude Code Multiplexer

amux wraps tmux to run dozens of Claude Code agents in parallel — and keep them running unattended. A background thread snapshots every session every 60s: auto-compacts when context drops below 20%, restarts and replays on thinking-block corruption, and unblocks sessions stuck waiting for input. Every session gets `$AMUX_SESSION` and `$AMUX_URL` injected at startup; the global memory file shared across all sessions contains the full REST API reference, so agents can discover peers, claim tasks atomically, and coordinate without being explicitly programmed to do so.

No build step, no external services — Python 3 and tmux. Access everything from your browser, phone (PWA), or terminal.

<video src="amux.mp4" width="920" autoplay loop muted playsinline></video>

## How it works

**Status detection** — amux parses Claude Code's actual terminal output after stripping ANSI escapes. No API hooks, no patches, no modifications to Claude Code. Unicode dingbat spinners (U+2700–27BF) + trailing ellipsis = working. "Enter to select" / "❯ 1. Yes" UI chrome = waiting for input. Completed spinner + "for Xm Ys" = idle. Status streams to all clients via SSE.

**Self-healing** — a background thread snapshots every session every 60s:
- Context < 20%? Sends `/compact` automatically (5-minute cooldown).
- `redacted_thinking … cannot be modified` detected? Restarts the session and replays the last user message.
- Session stuck waiting for input for 2+ snapshots? With `CC_AUTO_CONTINUE=1`, auto-responds based on prompt type.
- Safety-prompt UI chrome ("Esc to cancel") detected in a YOLO session? Auto-answers with "1" — that marker never appears on open-ended model questions, so the distinction is reliable.

**Orchestration** — every session gets `$AMUX_SESSION` and `$AMUX_URL` at startup. The global memory file (`GET /api/memory/global`, shared across all sessions) contains the full REST API reference, so any agent can discover peers, peek their output, delegate tasks, and atomically claim board items without being explicitly told how.

**Single file** — everything lives in `amux-server.py`: ~12,000 lines of Python `ThreadingHTTPServer` + inline HTML/CSS/JS dashboard. No build step, no npm, no Docker. Save the file and it restarts itself via `os.execv`.

## Install

```bash
git clone <repo> && cd amux
./install.sh
```

Requires `tmux` and `python3`. Installs `amux` (and alias `cc`) to `/usr/local/bin`.

## Quick Start

```bash
# Register a session
amux register myproject --dir ~/Dev/myproject --yolo

# Start it headless
amux start myproject

# Open the terminal dashboard
amux

# Or serve the web dashboard
amux serve
```

## CLI Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `amux` | | Interactive terminal dashboard |
| `amux register <name> --dir <path>` | `reg` | Register a new session |
| `amux start <name>` | | Start a session headless |
| `amux stop <name>` | `kill` | Stop a running session |
| `amux attach <name>` | `a` | Attach to a session's tmux |
| `amux peek <name> [lines]` | `p` | View session output without attaching |
| `amux send <name> <text>` | | Send text/command to a session |
| `amux exec <name> [flags] -- <prompt>` | `run` | Register, start, and send a prompt in one shot |
| `amux ls` | `list` | List all sessions |
| `amux info <name>` | | Show session details |
| `amux rm <name>` | `del` | Remove a session |
| `amux start-all` | | Start all registered sessions |
| `amux stop-all` | | Stop all running sessions |
| `amux defaults` | `config` | Manage default flags |
| `amux serve` | `web` | Start the web dashboard |

Session names support prefix matching — `amux attach my` resolves to `myproject` if unambiguous.

## Claude Code Flags

Pass any Claude Code flag when registering:

```bash
amux register api --dir ~/Dev/api --yolo --model sonnet
amux register fast --dir ~/Dev/fast --model haiku --dangerously-skip-permissions
```

## Web Dashboard (PWA)

`amux serve` starts an HTTPS server (default port 8822):

```bash
amux serve           # serves on :8822
amux serve 9000      # custom port
```

### Session Management

- **Live status badges** — working / needs input / idle, derived from terminal output parsing
- **Expand cards** — token stats, send commands, quick-action chips (`/compact`, `/status`, `/cost`, Ctrl-C)
- **Peek mode** — full scrollback with search, highlight, and send bar. Works on stopped sessions (saved to disk every 60s)
- **Multi-pane workspace** — full-screen tiled layout; watch multiple agents side by side with per-pane send bars. Save/restore named layout profiles
- **YOLO auto-responder** — with `--dangerously-skip-permissions`, auto-answers Claude Code's internal safety prompts by matching "Esc to cancel" UI chrome (never present on model-level questions)
- **Auto-continue** — `CC_AUTO_CONTINUE=1` in a session's env unblocks sessions stuck waiting for input after ~60s
- **Conversation fork** — clone any session's full JSONL history into a new session to branch an exploration without losing the original thread
- **Git conflict detection** — warns when two sessions share the same directory and branch; one-click helper to create an isolated `session/{name}` branch
- **AI-suggested branch names** — Claude Haiku generates contextual branch name suggestions from session name and goal
- **YOLO mode toggle** — `--dangerously-skip-permissions` per session, toggled from the card menu
- **Model switching** — change model from the menu; automatically sends `/model` to running sessions
- **File attachments** — paste images with Ctrl-V, drag-and-drop onto the send bar, or click 📎. Supports images, PDFs, text, CSV, JSON, and log files (20MB limit)
- **File path linkification** — clickable file paths in peek output open syntax-highlighted previews
- **Connect tmux sessions** — adopt existing tmux sessions not created by amux

### Agent Orchestration

Sessions can coordinate with each other via the HTTP API. Every session gets two env vars injected at startup:

- `$AMUX_SESSION` — the session's own name
- `$AMUX_URL` — the API base URL (`https://localhost:8822`)

The global memory file (shared across all sessions via `GET/POST /api/memory/global`) contains the full inter-session API reference, so Claude can use these patterns without being explicitly told:

```bash
# See what other sessions are running
curl -sk $AMUX_URL/api/sessions | python3 -c \
  "import json,sys; [print(s['name'], s['status']) for s in json.load(sys.stdin) if s['running']]"

# Send a message to another session
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"text":"please write tests for auth.py and report back"}' \
  $AMUX_URL/api/sessions/worker-1/send

# Atomically claim a task (CAS: only succeeds if unclaimed)
curl -sk -X POST $AMUX_URL/api/board/PROJ-5/claim

# Watch another session's output
curl -sk "$AMUX_URL/api/sessions/worker-1/peek?lines=50" | \
  python3 -c "import json,sys; print(json.load(sys.stdin).get('output',''))"
```

The global memory contains the full API reference, so just tell an orchestrator in plain English:

> "Find the worker-1 session and ask it to implement the login endpoint, then check back in 30 seconds"

### Board (Kanban)

A built-in kanban board backed by SQLite (WAL mode):

- **Atomic task claiming** — `POST /api/board/:id/claim` uses `UPDATE … RETURNING` (SQLite 3.35+) to atomically claim a task. Multiple agents can race without a lock service or queue broker
- **Auto-generated issue keys** — derived from session name prefix (e.g., VAN-1, AMUX-3) via atomic counter
- **iCal sync** — RFC 5545 feed auto-uploaded to S3 with board items' due dates; maps board status to iCal STATUS. Subscribe in Google Calendar or Apple Calendar
- **Session linking** — associate items with sessions; click session badges to filter
- **Custom columns** — add/rename/reorder kanban columns beyond the defaults
- **REST API** — full CRUD at `/api/board` for external integrations
- **Soft deletes** — deleted items preserved as tombstones for delta sync

```bash
# Add an item
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"title":"Fix auth bug","status":"todo","session":"myproject"}' \
  https://localhost:8822/api/board

# Atomically claim it
curl -sk -X POST https://localhost:8822/api/board/MYPROJECT-1/claim
```

### Self-Healing Background Loop

The 60s snapshot loop monitors all running sessions:

| Condition | Action |
|-----------|--------|
| Context < 20% remaining | Sends `/compact` (5-min cooldown) |
| `redacted_thinking … cannot be modified` | Restarts session + replays last user message |
| Status = `waiting` for 2+ snapshots + `CC_AUTO_CONTINUE=1` | Auto-responds based on prompt type |
| YOLO session + safety prompt UI | Auto-answers (6s cooldown) |

Alert types (`auto_compact`, `thinking_reset`, `auto_continue`) are broadcast to all SSE clients as toast notifications.

### Scheduled Tasks

Built-in cron with no external dependencies:

- **Frequencies** — once, hourly, daily, weekly (weekday + time), monthly (day + time)
- **Next-run computed atomically** in SQLite; no race conditions, handles missed fires
- **Sends raw tmux commands** to the target session (e.g., `/compact`, `/status`, custom prompts)
- **30s polling loop** in the background; no crontab, no systemd timer

### Real-Time Updates (SSE)

- **`GET /api/events`** — SSE stream pushing session and board changes every 2s
- **Shared server cache** — multiple browser tabs share subprocess results (2s TTL)
- **Heartbeat** — every 15s to keep connections alive through NAT/proxies
- **Auto-fallback** — 3 SSE failures → 5s polling
- **Delta sync** — `GET /api/sync?since=<unix_ts>` returns only changed issues, soft-delete aware; fires on SSE reconnect to catch offline changes

```bash
# Test the SSE stream directly
curl -sk -N https://localhost:8822/api/events
```

### Offline / PWA

Install as a PWA on iOS or Android. Triple-layer persistence for offline resilience:

1. **Service Worker Cache API** — app shell pre-cached at install
2. **localStorage** — full HTML backup (fast restore; iOS can purge between sessions)
3. **IndexedDB v2** — full issue + status mirror (survives localStorage eviction)

- **Background Sync** (Chrome/Edge) — service worker replays queued operations automatically on reconnect, even if the tab is closed
- **Draft sessions** — create sessions offline, auto-synced on reconnect
- **Connection indicator** — "Live" / "Offline (N pending)" pill in the header

### Token Stats

- Daily totals and per-session breakdown from Claude Code's JSONL logs
- Tracks `cache_read_input_tokens` and `cache_creation_input_tokens` separately
- Deduplicates log entries by `(input, cache_read, output)` signature — restarts don't double-count
- Reset-to-baseline button for period comparisons

### HTTPS & Tailscale

Auto-generates TLS certs in order:

1. **Tailscale** — real Let's Encrypt cert via `tailscale cert`; trusted everywhere with zero setup
2. **mkcert** — locally-trusted CA; no browser warnings on the same machine
3. **Self-signed** — fallback via openssl

```bash
# With Tailscale (recommended for phone access)
amux serve
# → https://your-machine.tailnet-name.ts.net:8822

# Disable TLS
amux serve --no-tls
```

For iOS PWA without Tailscale: install the mkcert root CA via AirDrop, then trust it in Settings > General > About > Certificate Trust Settings.

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | GET | List all sessions with status, preview, tokens |
| `/api/sessions` | POST | Create a new session |
| `/api/sessions/<name>/start` | POST | Start a session |
| `/api/sessions/<name>/stop` | POST | Stop a session |
| `/api/sessions/<name>/send` | POST | Send text to a session |
| `/api/sessions/<name>/keys` | POST | Send raw tmux keys |
| `/api/sessions/<name>/peek` | GET | Get session output |
| `/api/sessions/<name>/info` | GET | Session details |
| `/api/sessions/<name>/stats` | GET | Token usage stats |
| `/api/sessions/<name>/config` | PATCH | Update config (rename, model, dir, tags, yolo, auto-continue, etc.) |
| `/api/sessions/<name>/delete` | POST | Delete a session |
| `/api/sessions/<name>/duplicate` | POST | Duplicate session config |
| `/api/sessions/<name>/clone` | POST | Fork conversation (clone JSONL history) |
| `/api/sessions/<name>/clear` | POST | Clear tmux scrollback |
| `/api/sessions/<name>/memory` | GET/POST | Per-session memory file |
| `/api/sessions/connect` | POST | Adopt an existing tmux session |
| `/api/tmux-sessions` | GET | List unregistered tmux sessions |
| `/api/board` | GET | List board items |
| `/api/board` | POST | Create a board item |
| `/api/board/<id>` | GET/PATCH/DELETE | Read/update/delete an item |
| `/api/board/<id>/claim` | POST | Atomically claim a task (CAS) |
| `/api/board/clear-done` | POST | Remove all done items |
| `/api/board/statuses` | GET/POST | List or add custom columns |
| `/api/board/statuses/<id>` | PATCH/DELETE | Rename or remove a column |
| `/api/sync` | GET | Delta sync (`?since=<unix_ts>`) |
| `/api/events` | GET | SSE stream (sessions + board + alerts) |
| `/api/memory/global` | GET/POST | Global memory shared across all sessions |
| `/api/stats/daily` | GET | Daily token stats |
| `/api/stats/reset` | POST | Reset token counters |
| `/api/calendar.ics` | GET | RFC 5545 iCal feed of dated board items |
| `/api/file` | GET | Read file contents (peek file previews) |
| `/api/autocomplete/dir` | GET | Directory path autocomplete |

## Session Logs

amux snapshots all running sessions to `~/.amux/logs/` every 60s (up to 10MB per session):

- Stopped sessions still show preview and full peek output
- Output survives server restarts
- Peek mode for stopped sessions loads from saved log

## File Layout

```
~/.amux/
  sessions/            # session .env files (CC_DIR, CC_FLAGS, CC_AUTO_CONTINUE, etc.)
  logs/                # session scrollback snapshots (10MB max each)
  tls/                 # auto-generated TLS certs
  amux.db              # SQLite database (issues, statuses, schedules, counters)
  uploads/             # file attachments sent to agents
  memory/              # per-session and global memory files
  token_baseline.json  # token counter reset baseline
  defaults.env         # global default flags
  server.env           # persistent server config (S3 bucket, etc.)
```

## Configuration

### Global defaults

```bash
amux defaults show           # view current defaults
amux defaults edit           # open in $EDITOR
amux defaults reset          # clear all defaults
```

```bash
# In ~/.amux/defaults.env:
CC_DEFAULT_FLAGS="--dangerously-skip-permissions"
```

### Per-session config

Each session is a plain env file in `~/.amux/sessions/<name>.env`:

```bash
CC_DIR="/Users/you/Dev/project"
CC_FLAGS="--model sonnet --dangerously-skip-permissions"
CC_DESC="Main backend work"
CC_TAGS="backend,api"
CC_PINNED="1"
CC_AUTO_CONTINUE="1"          # auto-unblock when waiting for input
CC_AUTO_CONTINUE_MSG="continue" # message sent when interrupted
```

### Server config — `~/.amux/server.env`

```bash
AMUX_S3_BUCKET=my-bucket      # iCal feed upload target
AMUX_S3_KEY=amux/calendar.ics
AMUX_S3_REGION=us-east-2
```

After editing, `touch amux-server.py` to trigger a reload.

## Security

amux is a **local-first tool** designed for Tailscale or localhost. It has no built-in authentication:

- **Network access** — use Tailscale (recommended) or bind to localhost only. Never expose port 8822 to the internet.
- **File access** — `/api/file` reads any path the server user can access. Treat like any local dev server.
- **CORS** — wildcard CORS intentionally set for local use.

For cloud deployments, the [GCP setup](cloud/) creates a VM that blocks all inbound internet traffic except Tailscale UDP.

## Architecture

Everything lives in `amux-server.py`. Python `ThreadingHTTPServer` with inline HTML/CSS/JS — no build step, no npm, no Docker.

- **Server** — `BaseHTTPRequestHandler` with manual routing, TLS, and `os.execv` self-restart on file save
- **State** — session configs in `.env` files; board/issues/schedules in SQLite (WAL mode); tmux for process isolation
- **Sync** — SSE push for real-time updates; delta sync endpoint for offline catch-up; `_sse_cache` shared across tabs (2s TTL)
- **Self-healing** — 60s snapshot loop: context watchdog, thinking-block recovery, auto-continue
- **Offline** — IndexedDB + localStorage + SW Cache API triple-layer; Background Sync for queue replay; 3-layer restoration order on startup
- **Client** — vanilla JS SPA; no framework; Sortable.js for drag-and-drop; GridStack for workspace layout
