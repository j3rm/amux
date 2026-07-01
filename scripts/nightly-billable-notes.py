#!/usr/bin/env python3
"""Nightly billable-notes writeup dispatcher.

Fires from SCHED-N at 23:30 daily. Enumerates every CD-*.env session (skipping
archived), and POSTs a board item to each one telling the agent to package
its last-24h work as a billable-notes writeup, send it to Cypra-PAA, and
post a self-follow-up to verify Cypra actually created the notes.

Deterministic; zero LLM tokens. The agents do their per-client work when they
next wake (nudged by the 15-min watchdog if idle).

The billable-writeup instructions live in a template below so all CD-* agents
receive an identical procedure and Cypra receives a consistent format that's
easy to parse into Zoho Projects billable notes.
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

AMUX_URL = os.environ.get("AMUX_URL", "https://localhost:8822")
CC_SESSIONS = Path.home() / ".amux" / "sessions"
BILLING_TARGET = "Cypra-PAA"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        AMUX_URL + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def _parse_env(env_file: Path) -> dict:
    cfg = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _cd_sessions() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(CC_SESSIONS.glob("CD-*.env")):
        name = f.stem
        cfg = _parse_env(f)
        if cfg.get("CC_ARCHIVED") == "1":
            continue
        out.append((name, cfg))
    return out


TASK_TEMPLATE = """NIGHTLY BILLABLE-NOTES WRITEUP for {date}

Auto-posted by the nightly billable-notes dispatcher. Review your work for
this client in the last 24 hours and package it for Cypra-PAA to log as
billable notes in Zoho Projects.

## What to do

1. **Figure out what you did.** Sources:
   - `git log --since='24 hours ago'` in your client repos under $CLIENT_ROOT
   - The board — items assigned to you that you PATCHed to done, review, or
     verified in the last 24h. Query:
       curl -sk $AMUX_URL/api/board | python3 -c "
       import json,sys,os,time
       s=os.getenv('AMUX_SESSION',''); cutoff=int(time.time())-86400
       for i in json.load(sys.stdin):
         if i.get('session')==s and i.get('updated',0)>=cutoff and i['status'] in ('done','review','verified'):
           print(i['id'], i['status'], i['title'][:80])
       "
   - Any amux notes you wrote today.
   - Your own memory of what the client asked and what you delivered.

2. **For each meaningful task, decide:**
   - A one-line description in **client-facing language** (no AI / model /
     API-internals talk — the client is going to see this).
   - Time in hours or minutes (your best estimate — if you don't have exact
     timings, be conservative and round up to the nearest 15 min).
   - Whether it was billable (default yes; skip pure system/substrate
     housekeeping).

3. **Post ONE new board item assigned to `Cypra-PAA`** with the exact shape
   below. Do NOT send this via channel or /send — the board queue keeps it
   organized and prevents cross-agent interruption.

   ```
   title:  Billable notes: {client} — {date}
   session: Cypra-PAA
   status: todo
   org:    (leave unset — Cypra-PAA has its own routing)
   desc:   [use the CLIENT/DATE/TASKS/TOTAL format below]
   ```

   Desc format (copy-paste and fill in):

   ```
   CLIENT: {client}
   DATE: {date}
   SOURCE_SESSION: {session}
   PROJECT_HINT: (project name in Zoho Projects, or best guess)

   TASKS:
   - [1.5h] <one-line client-facing description>
   - [0.5h] <one-line client-facing description>
   - [2h]   <one-line client-facing description>

   TOTAL: <N>h billable

   Please create Zoho Projects billable notes for these tasks. Reply on this
   board item by PATCHing with status=done and desc containing either:
     CREATED: <comma-separated Zoho Projects note IDs>
   or
     BLOCKED: <one-line reason and what you need>
   ```

4. **Post a SECOND board item assigned to yourself** as a follow-up to
   verify Cypra actually processed your notes. Shape:

   ```
   title:  Verify Cypra billable-note creation for {date}
   session: {session}
   status: todo
   desc:   Check whether Cypra-PAA PATCHed board item <the-cypra-item-id-you-got-back-in-step-3>
           to done with CREATED: <note ids>. If not done or BLOCKED: within 24h,
           surface this pending task to Jeremy on next engagement — do NOT let it
           silently sit.
   ```

5. **PATCH THIS ITEM to status=done** with a short summary in desc:
   ```
   Posted billable notes to Cypra as <cypra-item-id>. Follow-up on <followup-item-id>.
   ```

## If you did no billable work for {client} in the last 24 hours

Still PATCH this item to done with desc: `No billable work today.` No need
to post anything to Cypra or a self-follow-up.

## Rules

- Board items only. Do NOT channel or /send Cypra — that interrupts. Board
  is queue-based and lets Cypra process each writeup in order.
- Client-facing language. Skip AI / model / API-internals talk. Cypra is
  going to render these into Zoho Projects notes the client can read.
- Round conservatively on time. If you don't remember exactly, round UP to
  the nearest 15 minutes per task.
- One writeup per client per day. If you have work across multiple projects
  for the same client, group into one billable-notes item, one project hint
  per line if needed.
"""


def main() -> int:
    yesterday = (date.today() - timedelta(days=1)).isoformat()  # yesterday's date
    today = date.today().isoformat()
    sessions = _cd_sessions()
    if not sessions:
        print("No CD-* sessions found — nothing to dispatch.")
        return 0

    posted = []
    errors = []
    # Use today's date so the writeup is "for today's work" from the CD-*
    # perspective; the item lands at 23:30 which is close enough.
    for name, cfg in sessions:
        client = cfg.get("CC_DESC", "").split(" — ")[0].strip() or name.removeprefix("CD-")
        body = {
            "title": f"Nightly billable-notes writeup: {client} — {today}",
            "session": name,
            "status": "todo",
            "desc": TASK_TEMPLATE.format(date=today, client=client, session=name),
        }
        try:
            item = _post("/api/board", body)
            posted.append(f"{name}:{item.get('id')}")
        except Exception as e:
            errors.append(f"{name}:{type(e).__name__}")

    summary = (
        f"Nightly billable-notes dispatch {today}: "
        f"{len(posted)} posted, {len(errors)} errors. "
        + " ".join(posted[:20])
        + (f" ERRORS: {' '.join(errors)}" if errors else "")
    )
    print(summary)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
