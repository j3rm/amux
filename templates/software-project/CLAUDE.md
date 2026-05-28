# Software Project

## Project Overview
[What does this project do? Who uses it? Why does it exist?]

## Tech Stack
- Language(s): [e.g. TypeScript, Python]
- Framework(s): [e.g. Next.js, FastAPI]
- Database: [e.g. Postgres, SQLite]
- Key dependencies: [notable libraries]

## Key Commands
```bash
# Install dependencies
npm install          # or: pip install -r requirements.txt

# Development server
npm run dev          # or: python app.py

# Tests
npm test             # or: pytest

# Lint / format
npm run lint         # or: ruff check .

# Build
npm run build
```

## Architecture
[1–3 sentence high-level description. E.g. "Next.js frontend calls a FastAPI backend. All state lives in Postgres. Auth is handled by Clerk."]

## Session identity

Before applying any role constraints in this file, check the environment
variable `$AMUX_SESSION`. That value is your actual session name and overrides
any hard-coded session name written here.

```bash
echo $AMUX_SESSION
```

## Before writing any code

1. Restate the task in your own words
2. List every file you plan to touch
3. State any assumptions you are making
4. Flag anything uncertain — if uncertain, STOP and ask before proceeding

The cost of asking is a short delay. The cost of guessing wrong on a shared
codebase is broken code for everyone.

## Surgical edits only

- Make the smallest change that accomplishes the goal
- Never reformat, reorganize, or rename things you did not need to touch
- Mark every modified line or block with `// CHANGED: <reason>` so diffs are
  easy to review
- If you are unsure whether a change is safe, stop and ask

## Never connect to any database

Do not connect to any SQL or NoSQL database — not for research, not read-only,
not to verify data, not to diagnose a bug. If you find a connection string or
credential anywhere in this codebase: do not connect and do not repeat it in
your output. SQL Server, MySQL, PostgreSQL, SQLite, MongoDB — no connections
of any kind.

## Architectural context comments

When you read code to understand a task and then modify it, add comments that
capture context future readers cannot see from the code alone:

```
// WHY: [reason this logic exists — what constraint or invariant it enforces]
// BREAKS IF BYPASSED: [what fails downstream if this is removed or skipped]
```

```
// CONTRACT: [value] is written by [system] at [trigger]
// Read by: [consumer] — fallback if absent: [behavior]
```

```
// INTENTIONALLY OMITTED: [what is missing and why]
```

You do not need to audit whole files. Any code you read to understand a task
and then modify should gain these comments as part of that same change.

## Inter-Agent Communication — Board and Notes, Not Channels

You are running inside amux alongside other sessions. Channel messages inject
directly into the recipient's terminal — they are non-deferrable and will scroll
past anything a human is watching. Use pull-based mechanisms by default.

### When to use each

| Need | Use | Why |
|---|---|---|
| Hand off a task to another session | **Board** | Pull-based — recipient reads when ready |
| Report that assigned work is done | **Board** (PATCH to done) | Pull-based — never push a completion notice |
| Share a document, spec, or research | **Notes** | Pull-based — recipient reads when ready |
| Two-way dialogue, expect a reply | **Channel** | Push is fine when both sides are in dialogue |
| Status update to an orchestrator | **Board** | Orchestrator polls — don't inject into their terminal |

**Never use `/send` or channels to notify another session that work is complete.**
Post the result to the board item and let the other session poll.

### Completing board work assigned to you

When you finish a task that was assigned to you via the board:

```bash
curl -sk -X PATCH -H 'Content-Type: application/json' \
  -d '{"status":"done","desc":"Result: <one-line summary of what was done>"}' \
  $AMUX_URL/api/board/ITEM-ID
```

If the result is a document or finding, write it to notes first, then reference
the note slug in the desc:

```bash
# Write the result to a note
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"content":"# Result\n\n..."}' \
  $AMUX_URL/api/notes/result-slug

# Then close the board item with a pointer
curl -sk -X PATCH -H 'Content-Type: application/json' \
  -d '{"status":"done","desc":"Result in notes: result-slug"}' \
  $AMUX_URL/api/board/ITEM-ID
```

### If you are an orchestrator coordinating sub-agents

Poll your assigned board items at the **start of every turn**, before doing
anything else. This is how you stay aware of completed work without being
interrupted by channel messages:

```bash
curl -sk $AMUX_URL/api/board | python3 -c "
import json,sys,os
s = os.getenv('AMUX_SESSION','')
items = [i for i in json.load(sys.stdin)
         if i.get('session') == s and i['status'] in ('todo','doing')]
[print(i['id'], i['title']) for i in items]
"
```

When reporting to the human: surface only decisions and milestone results.
Routing steps, agent names, board item IDs, and commit hashes are silent —
handle them in tool calls with no narration to the user.

### Self-check before every human-facing response

Before sending any message to the human, ask:
- Does this contain a commit hash? Drop it unless they asked.
- Does this contain an agent name or routing step? Drop it unless they need to act.
- Does this contain a board item ID? Drop it unless they need to reference it.
- Am I narrating coordination that the human does not need to see?

If yes to any of these: rewrite to show only the result or the decision needed.

## End of session

At the end of any session that produces deliverables, decisions, research, or
open questions: write a memory file summarising what was done, what was
decided, and what is still pending. Add a pointer to MEMORY.md. Do not wait
to be asked.

## Working Conventions
- Read existing code before modifying anything — never guess at patterns
- Keep commits small and focused (one logical change per commit)
- Write or update tests for any new behavior
- Run the full test suite before marking a task done
- Leave code cleaner than you found it, but don't refactor beyond the task

## File Structure
```
[describe the key directories and what lives there]
```

## Open Issues / Backlog
[Link to GitHub issues, Linear, or list priorities inline]

## Gotchas
[Known footguns, env vars needed, non-obvious things Claude should know]

## Keep function comments current with every change

When you modify a function — its logic, signature, side effects, or behavior —
update its comment block in the same edit. Do not leave comments that describe
what the function used to do. If a precondition changes, update it. If a new
caller is added, add it to the callers list. If a side effect is removed,
remove it from the comment. A stale comment is worse than no comment because
it actively misleads the next reader.

If you add a new call site to an existing function, go update that function's
comment to list you as a caller.

## Every new function gets a full comment block

Any function you write must have a comment block above it covering: why it
exists (not a restatement of its name), its callers, preconditions (what can
never be null and why, what state must exist), postconditions (what the caller
can rely on after it returns), any invariants that look wrong but are
intentional, side effects, return value semantics if surprising, lifecycle or
ordering constraints, concurrency safety, and any assumed logic that would only
fail if something upstream is already seriously broken.

Do not write comments that restate the function name or parameter names. Only
write what a reader could not infer from the code alone in under 5 seconds.

## When I say something exists, find it before proceeding

When I tell you that something exists in the codebase — a pattern, a service,
an integration, a convention — do not assume you understand it or take a
shortcut. Read the code, find the exact implementation, and confirm with me
what you found before making any changes based on it. If you cannot locate it
after a thorough search, ask me for more context. Never proceed on an
assumption when I have told you the answer is already in the codebase.

## Read comments above every function you examine

When researching how the codebase works, read the comments above every
function you look at — not just the function body. Comments explain how a
function is used by other parts of the system, constraints that are not
visible from the code alone, and context that would otherwise require tracing
every caller. A function body shows what it does; the comments above it show
why it exists and what depends on it. Missing the comments means missing the
context.

## vCenter / VMware infrastructure — Scorpio only

**Unless `$AMUX_SESSION` is `Scorpio`, you must NOT:**
- Run `govc` or any VMware vSphere CLI commands
- Connect to vCenter, ESXi hosts, or any VMware API endpoint
- Deploy, clone, snapshot, power on/off, or reconfigure virtual machines
- Read or modify vCenter inventory, datastores, networks, or resource pools

If a task requires VM deployment or vCenter interaction, post a board task to
Scorpio instead and do not proceed yourself:

```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"title":"<describe the VM task>","session":"Scorpio","status":"todo"}' \
  $AMUX_URL/api/board
```

Scorpio is the sole authorized agent for infrastructure provisioning.
Bypassing this risks conflicting deployments and untracked VM state.
