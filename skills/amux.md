---
description: Interact with the amux multiplexer — board, memory, sessions, and more
allowed-tools: Bash, Read, Edit, Write
argument-hint: [board|memory|sessions|help] [args...]
---

# /amux — amux Session Integration

You are running inside an **amux** managed Claude Code session. amux is a local multiplexer that manages multiple Claude sessions, a shared kanban board, and per-session memory.

## amux API

Base URL: `https://localhost:8822` (self-signed TLS — always use `curl -sk`)

### Board

```bash
# List board items
curl -sk https://localhost:8822/api/board | python3 -m json.tool

# Add item (id is auto-derived from session name, e.g. KITTYKAT-1)
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"title":"...", "desc":"...", "status":"todo", "session":"SESSION_NAME"}' \
  https://localhost:8822/api/board

# Update item status
curl -sk -X PATCH -H 'Content-Type: application/json' \
  -d '{"status":"doing"}' https://localhost:8822/api/board/ITEM_ID

# Delete item
curl -sk -X DELETE https://localhost:8822/api/board/ITEM_ID
```

Board statuses: `todo` · `doing` · `done` (plus any custom columns)

### Sessions

```bash
# List sessions (name, running, dir, model, tags)
curl -sk https://localhost:8822/api/sessions | python3 -m json.tool

# Send a message to a session
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"text":"your message"}' https://localhost:8822/api/sessions/SESSION_NAME/send

# Get terminal output from a session
curl -sk https://localhost:8822/api/sessions/SESSION_NAME/peek
```

### Memory

```bash
# Read this session's memory
curl -sk https://localhost:8822/api/sessions/SESSION_NAME/memory

# Update this session's memory (replaces content)
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"content":"# My Notes\n..."}' https://localhost:8822/api/sessions/SESSION_NAME/memory

# Read/write global memory (shared by all sessions)
curl -sk https://localhost:8822/api/memory/global
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"content":"..."}' https://localhost:8822/api/memory/global
```

## Determining the Current Session Name

The current amux session name can be inferred from the tmux session:
```bash
tmux display-message -p '#S' | sed 's/^amux-//'
```
Or from `$TMUX` environment variable context. If you can't determine it, ask the user.

## Instructions

The user's request is: **$ARGUMENTS**

Parse the arguments to determine what the user wants:

- **`board`** or **`board list`** → list current board items, grouped by status
- **`board add <title>`** → add an item to the board; infer session from current tmux session
- **`board done <id>`** → mark an item done
- **`memory`** or **`memory show`** → show current session's memory content
- **`memory update`** → read the current MEMORY.md, extract useful facts from recent context, update via API
- **`sessions`** → list all amux sessions with their status
- **`help`** or empty → show a brief summary of available /amux commands
- **anything else** → interpret as a natural language amux action and execute it

Always:
1. Determine the current session name first (use `tmux display-message` or ask)
2. Use `curl -sk` (self-signed cert)
3. Format output clearly — tables for lists, key facts for status
4. After adding/updating anything, confirm with the ID and brief summary
