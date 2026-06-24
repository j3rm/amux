# Server hooks and scripts (substrate features)

A reference for the non-obvious behaviors built into amux-server.py and the
out-of-process scripts that complement it. Most of these were added in the
2026-06-24 substrate-refactor session that retired RTG-Dispatch,
Ember-Dispatch, and AMUX-Watchdog as agents in favor of server-enforced
hooks plus one shell script.

If you're an agent reading this for the first time: nothing in here changes
HOW you do work. It changes WHO does the connective tissue between work
items. Routing, verdict cascade, audit-pair completion, escalation dedup,
and idle-nudging used to be done by Haiku agents reading prompts; now they're
deterministic server code.

---

## C3 — adjudication-already-applied (in `amux-server.py`)

**Trigger:** PATCH on any item whose assignee session ends in `-Research`
(RTG-Research, Ember-Research, future `*-Research` orgs).

**Behavior:** Extracts a `VERDICT: <PASS|PASS-WITH-WARNINGS|FAIL>` marker
from the item's desc (start-of-line, last-match-wins). Extracts the target
work-item id from the title first (audit/escalation titles follow
`ESCALATE <TARGET>:` / `ESC-<TARGET>:` / `AUDIT <TARGET>:` conventions),
falling back to the desc.

If the target is currently at status `review` or `doing`, the server
auto-PATCHes:
- PASS / PASS-WITH-WARNINGS → target `verified`
- FAIL → target `doing` (worker re-takes)

The cascade is recorded in the target's desc as a `[auto-applied YYYY-MM-DD
HH:MM by C3: ...]` line.

**Why this exists:** Before the hook, RTG-Dispatch (Haiku) had to scan
review-status RR-* items and apply verdicts manually. Haiku missed verdicts
frequently, leaving 28+ items stuck at review with completed adjudications.
C3 makes the application synchronous with the PATCH itself.

**Idempotency:** If the target is already in the resulting status, the
cascade is a no-op.

---

## C4 — audit-pair-complete-triggers-verify (in `amux-server.py`)

**Trigger:** PATCH on any item whose assignee session contains `-Audit-`
(RTG-Audit-Codex, RTG-Audit-Opus48, Ember-Audit-Codex, Ember-Audit-Opus48,
future `*-Audit-*`).

**Behavior:** Extracts this audit's verdict and target id. Looks up the
mirror auditor's session (`-Audit-Codex` ↔ `-Audit-Opus48` sibling) and
finds the most-recent non-discarded audit for the same target. If both
audits have verdicts:

- Both ACCEPT (PASS / PASS-WITH-WARNINGS) → target `verified`
- Both FAIL → target `doing`
- Mixed → no auto-action; the escalation path is the next layer

The escalation-mint gate (below) then prevents duplicate RR-/ER- on mixed
cases.

**Why this exists:** Same reason as C3 — Dispatch wasn't reliably acting on
closed audit pairs. C4 ensures every completed pair drives the target's
next status transition synchronously.

---

## RR-/ER- escalation-mint gate (server-enforced, in POST /api/board)

**Trigger:** POST creating an item assigned to a `*-Research` session.

**Behavior:** Two hard checks, both returning HTTP 409 on failure:

1. **Target-status guard.** Extracts the target id from title+desc, looks
   it up. If the target is at `verified` / `done` / `discarded`, or its
   title/desc contains `VOID`, reject 409 (`escalation-gate: target is
   settled`).
2. **24h cooldown.** Looks for any non-discarded item assigned to a
   `*-Research` session created in the last 86,400s referencing the same
   target. If found, reject 409 (`escalation-gate: 24h cooldown`,
   `prior_rr`, `prior_age_hours`).

**Why this exists:** The Dispatch prompt had logic for this but Haiku
applied it unreliably. Today's incident: 7 ghost RR-* mints all duplicating
prior adjudications. The gate now lives where it can't be skipped.

The full spec lives in the amux note `rtg-follow-up-gate`.

---

## RD-/ED- routing hook (server-enforced, in POST /api/board)

**Trigger:** POST creating ANY board item whose desc contains a `ROUTE_TO:
<session>` line within the first 200 chars / first 5 lines.

**Behavior:**

1. Parse `ROUTE_TO: <session>` (bare or quoted). Validate the named session
   exists in `~/.amux/sessions/*.env`. Unknown session → push `routing_error`
   alert to amux-helper, leave the RD untouched.
2. Parse optional `BLOCKED_BY: <id list>`. If any listed dep is not at
   status `verified` / `done`, the child task lands at `backlog` instead of
   `todo`.
3. Parse optional `CHILD_TITLE: <override>` (default = original title) and
   `CHILD_PREFIX: <PREFIX>` (default = `RA`).
4. Mint the child task with the full RD desc as the worker spec (so the
   worker sees the full directive verbatim). Session = ROUTE_TO target.
5. PATCH the RD to status `done` with a `[server-routed YYYY-MM-DD HH:MM
   → child=<id>]` marker appended.

**Why this exists:** Replaces the only natural-language work Dispatch was
doing (reading RD specs and cutting child tasks). With RTG-Research and
Ember-Research adopting `ROUTE_TO:` as a structured field, even the
routing becomes mechanical.

**Idempotency:** If the desc already contains `[server-routed`, the hook
skips.

**Missing ROUTE_TO:** Silent no-op. By convention this means the author
made a category error (item should have been a channel/note/RR instead of
a routing directive); the absence is the signal.

---

## Silently-dead session detector (in `amux-server.py`, snapshot section 4d)

**Trigger:** Every snapshot loop iteration (~5s).

**Behavior:** For every session whose tmux pane is alive (not archived),
runs `pgrep -f "claude.*--name <session>"`. If no claude process is found
for more than 60s consecutive:

1. Push `session_dead` alert (NOT in the default mute list — reaches
   Pushover).
2. If `CC_AUTO_CONTINUE=1`, auto-restart with the standard 90s debounce.

**Why this exists:** Existing section 4b was status-gated and missed today's
RTG-AzureBackup (Fable error loop, no shell prompt) and RTG-ActCloudPortal
(post-batch-PATCH death). 4d is intentionally broader — process-presence
only, no UI heuristic.

---

## Context-exhaustion auto-restart (in `amux-server.py`, snapshot section 4c)

**Trigger:** Every snapshot loop iteration. Scans tmux tail for either of:

- `CONVERSATION ENDED — TOKEN LIMIT EXCEEDED`
- `CONTEXT WINDOW EXHAUSTED — PREVIOUS SESSION ENDED`

(both em-dash and ASCII-hyphen variants accepted).

**Behavior:** Always emits a `context_exhausted` push alert. Auto-restarts
only if the session env has `CC_AUTO_RESTART_ON_CTX_LIMIT=1` (opt-in;
default off for interactive sessions where restart would just hit the same
wall, on for stateless schedule consumers like the watchdog where each
wake is a fresh prompt).

---

## Pushover alert muting (in `_push_alert`)

`AMUX_PUSHOVER_MUTED_ALERTS` in `~/.amux/server.env` is a comma-separated
list of alert types whose phone push is suppressed. The SSE event still
fires (dashboard sees it); only Pushover is filtered.

Currently muted (as of 2026-06-24):
`task_pickup, auto_compact, auto_continue, thinking_reset,
steering_delivered, scheduler, uncommitted`

Currently **not** muted (still reach the phone):
`auto_restart, rate_limit_manual, session_dead, context_exhausted,
routing_error`

---

## Watchdog script — `scripts/watchdog.py`

Replaces the AMUX-Watchdog agent. Runs every 15 min via SCHED-38
(`kind=shell`, `AMUX_URL=https://localhost:8822 /usr/bin/python3
/home/jwesley/.amux/scripts/watchdog.py`). The script is also tracked in
this repo at `scripts/watchdog.py` for backup/restore purposes.

**Behavior:** Deterministic, no LLM required.

1. GET `/api/board` → group todo/doing items by assignee session.
2. GET `/api/sessions` → identify each assignee's current API status.
3. For each session that is running AND API-status=idle AND has pending
   items: POST `/api/sessions/<name>/send` with a fixed nudge string.
4. Print a one-line summary per session (captured into
   `schedule_runs.note`).

**Hard rules baked in:** never claim, complete, PATCH, or change any
board item. Never start or stop sessions. Only nudge sessions that are
running AND idle.

---

## Migration history

| Date | Change | Commit |
|---|---|---|
| 2026-06-24 | Pushover mute list + commit-guard honored | `77ade8b` |
| 2026-06-24 | Context-exhaustion banner detector | `437110a` |
| 2026-06-24 | Server-side RR-/ER- escalation gate | `711b354` |
| 2026-06-24 | C3 + C4 cascade hooks | `72461a2` |
| 2026-06-24 | Silently-dead detector + watchdog script | `2a05383` |
| 2026-06-24 | RD-/ED- routing hook, Dispatch agents retired | `5693ae9` |
| 2026-06-24 | Hooks made org-agnostic (session-based) | `75e9485` |
| 2026-06-24 | Target-id extraction broadened beyond RTG prefixes | `863f5ff` |

---

## What was retired

- **AMUX-Watchdog agent** — replaced by `scripts/watchdog.py`. Env file at
  `~/.amux/sessions/AMUX-Watchdog.env` is marked `CC_ARCHIVED=1`.
- **RTG-Dispatch agent** — replaced by C3/C4/escalate-gate/RD-routing
  hooks. SCHED-40 disabled. Env file marked `CC_ARCHIVED=1`.
- **Ember-Dispatch agent** — same as RTG-Dispatch. SCHED-41 disabled.

All three sessions remain on disk in case rollback is ever needed.

---

## What persists across restarts

Server-side hooks and the snapshot-loop detectors live in `amux-server.py`
itself — they survive `os.execv` reloads and full process restarts.

The watchdog script lives at `~/.amux/scripts/watchdog.py` (and is tracked
in this repo at `scripts/watchdog.py` as a backup). Surviving a disk loss
requires the repo backup.

Schedule rows (SCHED-38 / SCHED-39 / SCHED-42 / SCHED-43) live in
`~/.amux/amux.db`. Surviving a disk loss requires the
`AMUX_BACKUP_REPO=git@github.com:j3rm/amux-config.git` daily backup.

Session env flags (`CC_AUTO_CONTINUE`, `CC_AUTO_RESTART_ON_CTX_LIMIT`,
`CC_ARCHIVED`) live in `~/.amux/sessions/*.env`. Same backup path.

Server env flags (`AMUX_PUSHOVER_MUTED_ALERTS`, `AMUX_COMMIT_GUARD`) live
in `~/.amux/server.env`. Same backup path.
