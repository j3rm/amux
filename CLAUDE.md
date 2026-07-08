# amux

Single-file project: everything lives in `amux-server.py` (Python server + inline HTML/CSS/JS dashboard).

## Structure

- `amux-server.py` — the server + dashboard (single file)
- `mcp.json` — centralized MCP server config (shared by local and cloud)
- `cloud/` — GCP VM provisioning (Terraform + setup script)
- `wiki/` — **fork documentation** (durable, survives disk/memory loss): features
  added vs upstream, the multi-agent orchestration architecture, changelog-vs-main,
  and the operations runbook. Start at `wiki/Home.md`. The orchestration system
  lives mostly outside this file (agent role files + schedule prompts) — the wiki
  is its only durable record.

## Workflow

- **Commit after every completed task.** When you finish a piece of work (bug fix, feature, refactor), immediately `git add amux-server.py && git commit` with a concise message. Don't batch multiple tasks into one commit.
- The server auto-restarts on file save (watches its own mtime), so changes are live immediately.
- Always verify Python syntax after edits: `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`

## Deploy

When the user says **"deploy"**, run the full pipeline:
1. `git add` changed files (typically `amux-server.py`)
2. `git commit` with a concise message
3. `git push origin main`

## Single-codebase rule (CRITICAL)

**`amux-server.py` is identical for both local (OSS) and cloud deployments — no exceptions.**

- Never add cloud-only or OSS-only code branches (no `if IS_CLOUD`, no `if os.environ.get('CLOUD')`).
- Features that differ between environments must be driven by headers/env vars injected by the gateway (e.g., `X-Amux-User-Email`) or by presence/absence of configuration, not by build-time flags.
- `cloud/docker/amux-server.py` must never be committed — it is auto-generated during deploy. It is in `.gitignore`.

## Server config — `~/.amux/server.env`

Persistent env vars for the server. Loaded at startup via `os.environ.setdefault` so process-level env always wins. Survives `os.execv` auto-restarts.

Example `~/.amux/server.env`:
```
AMUX_S3_BUCKET=ethan-personal
AMUX_S3_KEY=amux/calendar.ics
AMUX_S3_REGION=us-east-2
```

After creating/editing server.env, `touch amux-server.py` to trigger a reload.

## iCal / Google Calendar sync

Board items with `due` dates are exported as an iCal feed:
- Local: `GET /api/calendar.ics`
- Public S3 (for Google/Apple Calendar subscriptions): set `AMUX_S3_BUCKET` in `server.env`

S3 bucket config (one-time, already done on `ethan-personal`):
- Public access block: `BlockPublicAcls=true, IgnorePublicAcls=true, BlockPublicPolicy=false, RestrictPublicBuckets=false`
- Bucket policy grants `s3:GetObject` on `arn:aws:s3:::ethan-personal/amux/calendar.ics` only
- Public URL: `https://ethan-personal.s3.us-east-2.amazonaws.com/amux/calendar.ics`

The feed auto-uploads to S3 on every board write (POST/PATCH/DELETE). The dashboard's calendar subscription button shows the S3 URL directly when configured.

## Threads are for Jeremy only — never address another agent in a thread body

Threads inject to Jeremy alone. When an agent sends a thread message with
`to_session` blank, the server Pushovers Jeremy and notifies NO other agent —
even if the body opens with `Scorpio:` or `Addendum for iSchedule-Main:` or
`@Cypra`. The addressed agent will never see it. This is a real bug that has
happened (T-65/M-657, T-65/M-659 — iSchedule-Main wrote to Scorpio via Jeremy's
thread; Scorpio never got the message).

**Rules:**
- **Handoff to another agent** (you finished something, they need to act):
  POST /api/board with `session: "<their-name>"`. They poll their queue.
- **Two-way chatter with another agent** (you want a reply):
  POST /api/channels/`<your-session>`/`<their-session>`/messages.
- **Question or status for Jeremy**: threads, `to_session` blank. Body must
  be addressed to Jeremy — not to any other agent by name.

The server enforces this: a thread message with `from_session` set (agent),
`to_session` blank (→Jeremy), and a body containing `\b<KnownSession>:` for a
session other than yourself will be rejected 400 with a hint pointing to
board/channels.

## Browser Automation

Use `/chrome-cdp` for browser tasks. It connects directly to the user's live Chrome via CDP — real tabs, real cookies, no fresh browser.

```bash
node skills/chrome-cdp/scripts/cdp.mjs list           # list open tabs
node skills/chrome-cdp/scripts/cdp.mjs snap <target>   # accessibility tree
node skills/chrome-cdp/scripts/cdp.mjs shot <target>   # screenshot
node skills/chrome-cdp/scripts/cdp.mjs click <target> <selector>
node skills/chrome-cdp/scripts/cdp.mjs type <target> <text>
node skills/chrome-cdp/scripts/cdp.mjs eval <target> <js>
node skills/chrome-cdp/scripts/cdp.mjs nav <target> <url>
```

Requires Chrome remote debugging enabled (`chrome://inspect/#remote-debugging`) and Node.js 22+.

Claude Code, the amux server, and Chrome all run on the same desktop machine. Use `https://localhost:8822` for amux dashboard URLs.

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

## A Note from Jeremy — Quality Over Speed

Do not rush. Do not cut corners. Do not produce lazy or incomplete work hoping it won't be noticed.

If Jeremy suspects work was done carelessly, he will request a **full audit** of everything you have produced. An audit means re-examining every decision, every file, every commit, every output — and it is significantly more work than doing the job correctly the first time. Lazy work creates more work, not less.

**Work carefully. Work thoroughly. Own your output.**
