# Agent global memory — reference / backup

> **This is a durable backup of `~/.amux/memory/_global.md`** — the runtime file
> that the AMUX server auto-composes into every session's `MEMORY.md`. Edit the
> RUNTIME file (`~/.amux/memory/_global.md`) when you want to change what agents
> load; copy the change here afterward for offsite durability.
>
> Content below is the exact composed-memory prelude every AMUX agent (host or
> container) sees at session start.

---

# Shared Context

<!-- Add shared context for all sessions here -->

## amux inter-session API

You are session **$AMUX_SESSION** (env var). API base: **$AMUX_URL** (use `curl -sk` for both TLS and plain HTTP).

### Discover sessions
```bash
curl -sk $AMUX_URL/api/sessions | python3 -c "import json,sys; [print(s['name'], s.get('status',''), '-', s.get('desc','')) for s in json.load(sys.stdin)]"
```

### Peek at another session's output
```bash
curl -sk "$AMUX_URL/api/sessions/OTHER/peek?lines=100" | python3 -c "import json,sys; print(json.load(sys.stdin).get('output',''))"
```

### Send a message to another session
```bash
curl -sk -X POST -H 'Content-Type: application/json' \\
  -d '{"text":"<your message>"}' \\
  $AMUX_URL/api/sessions/OTHER/send
```

### Task delegation via board (recommended for orchestration)
```bash
# Create a board issue for yourself (always include your session name)
amux board add "Task title"   # preferred — auto-associates with $AMUX_SESSION
# Or via curl:
curl -sk -X POST -H 'Content-Type: application/json' \\
  -d "{\"title\":\"Task title\",\"session\":\"$AMUX_SESSION\"}" \\
  $AMUX_URL/api/board

# Post task for a specific session
curl -sk -X POST -H 'Content-Type: application/json' \\
  -d '{"title":"Do X","session":"worker-1","owner_type":"agent","status":"todo"}' \\
  $AMUX_URL/api/board

# Check tasks assigned to this session
curl -sk $AMUX_URL/api/board | python3 -c "
import json,sys,os
s=os.getenv('AMUX_SESSION','')
[print(i['id'],i['title']) for i in json.load(sys.stdin) if i.get('session')==s and i['status'] in ('todo','doing')]
"

# Claim a task atomically (prevents two sessions taking same task)
curl -sk -X POST -H 'Content-Type: application/json' \\
  -d '{"session":"'"$AMUX_SESSION"'"}' \\
  $AMUX_URL/api/board/TASK-ID/claim

# Mark task done
curl -sk -X PATCH -H 'Content-Type: application/json' \\
  -d '{"status":"done","desc":"Result: ..."}' \\
  $AMUX_URL/api/board/TASK-ID
```

### Threads — conversations with Jeremy or between agents

Threads replaced the old Questions/Inbox module in July 2026. A **thread** is
a conversation; a **message** is one entry inside it. Every message can be
replied to individually — `parent_id` points at the specific message.

**How to route questions and updates for Jeremy — this is the main rule:**

1. **Any question for Jeremy goes into Threads.** Not a board task, not
   `/send`, not a channel — Threads. That's where he sees his inbox and
   responds. Board tasks are for discrete work items; Threads are for
   conversation and questions where you expect a reply.
2. **Reuse an existing thread if the question relates to one.** Before
   starting a new thread, run `amux threads list` and check whether Jeremy
   already has an open thread with you on the same topic. If yes, reply
   into that thread with `amux threads reply <M-id>` so context stays
   together. Reserve new threads for genuinely unrelated topics.
3. **Start a new thread only when the topic is new.** e.g. a fresh
   escalation, a deploy blocker, a status/decision request on something not
   already in flight.
4. **Flag any incoming message that contains something you need to run
   later** (a SQL statement, a command, a file path) with
   `amux threads flag <M-id>` — Jeremy uses the Flagged summary at the top
   of the Threads UI, so flagging makes actionable content easy to find.

**Use the `amux threads` CLI** rather than raw curl — it fills in the
X-Amux-Session header automatically so message direction stays correct.

```bash
# Reply to a specific message. The CLI resolves the parent's thread for you.
amux threads reply M-42 "here's the answer..."

# Streaming (long answer): start partial, do work, finalize.
MID=$(amux threads reply --partial M-42 "working on it...")
# ...do the work...
amux threads finalize $MID "final answer"

# Start a new thread (e.g. escalate a question to Jeremy or another agent)
amux threads new Jeremy "Deploy blocked" "Migration script hit an ERROR on step 3..."

# List / show / flag / read
amux threads list
amux threads show T-12
amux threads flag M-42       # bookmark actionable content
amux threads read M-42       # mark a message read
```

**Direction rules:**
- If `AMUX_SESSION` is set (any agent session), the CLI puts your name in
  `X-Amux-Session` and the message is recorded as coming from you.
- Without that header, the server treats the sender as Jeremy — so agents
  MUST use the `amux` CLI (or set the header explicitly), not raw curl.

When Jeremy sends you a message via Threads, you'll get a board task with
title `Thread T-N: <thread title>` and a `desc` containing the `amux threads
reply` command pre-filled with the parent message ID. Just paste + fill in
your answer.

**When to use Threads vs. board vs. notes vs. channels:**
- **Threads** — back-and-forth conversation with Jeremy or another agent
  where you expect replies. Every message can be flagged, read, replied to.
- **Board** — discrete tasks and results. Not conversation. Mark done when
  finished.
- **Notes** — reference documents, research, write-ups meant to be read.
- **Channels** — persistent two-way threads between two agent sessions.

### Notes vs board issues — when to use each

**Use notes** (`/api/notes`) for: documents, write-ups, research, drafts, reference material, anything meant to be *read* by a human.
**Use board issues** (`/api/board`) for: tasks, todos, bugs, action items, anything meant to be *done* or *tracked*.

> Rule of thumb: "create a note about X" → `/api/notes`. "create a task/issue/todo for X" → `/api/board`.

```bash
# List all notes
curl -sk $AMUX_URL/api/notes

# Read a note
curl -sk $AMUX_URL/api/notes/my-note

# Create or update a note (content is plain text or Quill HTML)
curl -sk -X POST -H 'Content-Type: application/json' \\
  -d '{"content":"# Title\\n\\nBody text here"}' \\
  $AMUX_URL/api/notes/my-note

# Delete a note (moves to trash)
curl -sk -X DELETE $AMUX_URL/api/notes/my-note
```

### Google Drive — use the API, not Chrome MCP

Always use the Drive REST API directly. Do NOT open drive.google.com in Chrome MCP — that is slow and fragile.

```bash
# Get an access token (ADC — works after `gcloud auth application-default login`)
TOKEN=$(python3 -c "
import google.auth, google.auth.transport.requests
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive'])
creds.refresh(google.auth.transport.requests.Request())
print(creds.token)
")
PROJ="mixpeek-inference-463103"

# List files / search by name
curl -sk -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJ" \\
  "https://www.googleapis.com/drive/v3/files?q=name%3D'Partners'&fields=files(id,name,mimeType)"

# Create a folder
curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJ" \\
  -H 'Content-Type: application/json' \\
  -d '{"name":"My Folder","mimeType":"application/vnd.google-apps.folder"}' \\
  https://www.googleapis.com/drive/v3/files

# Create a folder inside a parent (use id from above)
curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJ" \\
  -H 'Content-Type: application/json' \\
  -d '{"name":"Sub Folder","mimeType":"application/vnd.google-apps.folder","parents":["PARENT_ID"]}' \\
  https://www.googleapis.com/drive/v3/files

# Create a Google Doc inside a folder
curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJ" \\
  -H 'Content-Type: application/json' \\
  -d '{"name":"My Doc","mimeType":"application/vnd.google-apps.document","parents":["PARENT_ID"]}' \\
  https://www.googleapis.com/drive/v3/files

# Write text content into a Google Doc (Docs API)
DOC_ID="..."  # id from create response
curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJ" \\
  -H 'Content-Type: application/json' \\
  -d '{"requests":[{"insertText":{"location":{"index":1},"text":"Hello world\\n"}}]}' \\
  "https://docs.googleapis.com/v1/documents/$DOC_ID:batchUpdate"
```

## Skills — how they work, how to add one

A skill is a reusable slash command (`/skill-name`) that Claude Code auto-loads
on every session start. Anything you find yourself doing more than once —
a curl invocation, a sequence, a pattern — is a candidate to save as a skill.

**Where they live:** SQLite `skills` table in `~/.amux/amux.db` (single source
of truth) → auto-synced as `.md` files to every session that could use them.
For host sessions: `~/.claude/commands/<name>.md`. For container sessions:
`~/.amux/orgs/<org>/home/.claude/commands/<name>.md` — one per org, so agents
in every org container get it too. **You do not manage the filesystem; the
server does.** Just use the API/CLI below.

**List existing:**
```bash
amux skills list
# or
curl -sk $AMUX_URL/api/skills | python3 -m json.tool
```

**Read a specific one before you override:**
```bash
amux skills get <name>
```

**Add or update:**
```bash
# From stdin (preferred — clean multi-line content):
amux skills set my-recipe < skill.md

# Or inline:
amux skills set my-recipe "$(cat <<'EOSKILL'
---
name: my-recipe
description: When to use this skill (Claude reads this to decide when to invoke)
---
# Your skill content
Instructions, code snippets, whatever a future agent needs to execute this.
EOSKILL
)"
```

On save, the server writes to SQLite AND immediately syncs the `.md` file to
host `~/.claude/commands/` AND every org container's shared home
`~/.amux/orgs/<X>/home/.claude/commands/`. Every future session in every org
sees the skill on start. Sessions currently running pick it up on their next
Claude Code restart.

**Delete:**
```bash
amux skills delete my-recipe
```

**Naming convention:** kebab-case, no slashes, matches how Claude displays
slash commands (`/my-recipe`). Keep the description tight — Claude uses it
verbatim to decide when to invoke your skill.

**When you should save a skill:**
- You solved a tricky curl / sql / git incantation and might need it again
- You discovered a pattern another agent in ANY org could benefit from
- You wrote a small script and prefer it available as `/name` instead of
  living as a one-off file somewhere

**When you should NOT save a skill:**
- One-time exploration or scratch code
- Sensitive credentials / tokens (skills sync to every org's container home
  — never put a secret in a skill)
- Very org-specific procedures that would confuse agents outside that org
  (put those in the org's `.agents/<agent>/CLAUDE.md` instead)
