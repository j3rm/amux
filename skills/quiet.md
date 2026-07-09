---
description: Remind an agent to move inter-agent coordination off the terminal and onto the board. Use when a session is sending noisy channel messages or routing chatter to the human's screen.
allowed-tools: Bash
argument-hint: [session-name or leave empty for current session]
---

# /quiet — Move Coordination Off the Terminal

The goal of this skill is to stop inter-agent chatter from appearing in the
human's terminal and redirect it to the board and notes where it belongs.

## What to do

### Step 1 — Identify the target session

If `$ARGUMENTS` is empty, this applies to **you** (the current session).
If `$ARGUMENTS` is a session name, this is a reminder to send to that session.

```bash
TARGET="${ARGUMENTS:-$AMUX_SESSION}"
echo "Applying quiet rules to: $TARGET"
```

### Step 2 — Self-check (if applying to yourself)

Review your recent behavior and answer each of these honestly:

- Have you sent a channel message to another session to report that work is done?
  → That should be a board PATCH, not a channel message.
- Have you included commit hashes, agent names, or board item IDs in messages to the human?
  → Those are coordination details. Drop them unless the human asked.
- Have you been narrating routing steps ("now delegating to X", "waiting for Y to complete")?
  → Handle these silently in tool calls. The human sees results, not coordination.
- Have you used `/send` to notify a session that was actively working?
  → That injects into their terminal mid-task. Use the board instead.

### Step 3 — Apply the rules going forward

**Board** — use for all of these:
- Assigning a task to another session
- Reporting work is done (PATCH to `done` with result in `desc`)
- Handing off a result for another session to read when ready

**Notes** — use for all of these:
- Documents, specs, research, findings
- Anything meant to be *read*, not *acted on immediately*

**Channels** — use only for:
- Two-way dialogue where you expect a reply in the same session
- Never to report completion, never to send status updates

**Human-facing messages** — contain only:
- Results and decisions they need to act on
- Nothing else

### Step 4 — If sending the reminder to another session

```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d "{\"text\":\"Quiet reminder: use the board for task handoffs and completion notices, not channels. Channel messages inject into the orchestrator's terminal and bury results from the human. PATCH your board items to done with the result in desc. Only use channels for two-way dialogue. Surface only results and decisions to the human — no routing steps, agent names, or commit hashes.\"}" \
  $AMUX_URL/api/channels/$AMUX_SESSION/$TARGET/messages
```

### The three rules in one sentence each

1. **Done with a task?** PATCH the board item to `done` — never channel the assigning session.
2. **Have a document?** Write it to notes — never paste it into a channel or the human's terminal.
3. **Talking to the human?** Show results and decisions only — drop all coordination details.
