#!/usr/bin/env python3
"""Nightly billable-notes writeup dispatcher.

Fires from SCHED-N at 23:30 daily. Enumerates every CD-*.env session (skipping
archived), and POSTs a board item to each one telling the agent to package
its last-24h work as a *provisional* billable-notes writeup, send it to
Cypra-PAA with evidence per item, and leave its OWN item in `doing` until
Cypra PATCHes it back with one of four outcome codes.

Deterministic; zero LLM tokens. The agents do their per-client work when they
next wake (nudged by the 15-min watchdog if idle).

Intake protocol (documented in the template and communicated to Cypra-PAA):

- The CD-* agent's writeup includes per-item evidence (commit hash / file
  mtime / transcript excerpt) so Cypra can dedup against existing Zoho logs.
- The CD-* agent's own nightly item stays in `doing` — NOT `done` — until
  Cypra closes it with one of:
    LOGGED — Zoho log ID <id>
    STAGED — added to billing ledger backlog
    SKIPPED — duplicate of existing log <id>
    NEEDS JEREMY INPUT — <reason>
  This prevents the item from being pruned before Cypra reviews it (2026-07-01
  AH-9 feedback from Cypra-PAA).
- The Cypra-facing item's desc includes SOURCE_ITEM: <CD-* nightly item id>
  so Cypra knows which item to PATCH the outcome back to.
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

Auto-posted by the nightly billable-notes dispatcher. Package your last-24h
work for this client as a PROVISIONAL billable-notes writeup. Cypra-PAA will
dedup against existing Zoho logs before anything gets billed — you just need
to surface what you did with enough evidence for Cypra to reconcile.

## What to do

1. **Figure out what you did in the last 24 hours.** Sources:
   - `git log --since='24 hours ago'` in your client repos under $CLIENT_ROOT
   - Board items assigned to you that you PATCHed to done, review, or
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

2. **Package each meaningful task with EVIDENCE.** For each:
   - **Description** in client-facing language (no AI / model / API-internals
     talk — the client will see this rendered as a Zoho Projects note).
   - **Time** in hours (your best estimate — round UP to nearest 15 min if
     unsure).
   - **Evidence**: at least one of `commit=<sha>`, `mtime=<file>`,
     `transcript=<one-line excerpt>`, or `board=<item-id>`. Evidence is
     REQUIRED per item — Cypra cannot dedup without it.
   - Skip pure system/substrate housekeeping.

3. **If you already know an existing Zoho log covers some of this work**
   (e.g. Jeremy manually logged 4h earlier that day), note it. Add
   `EXISTING_LOG_HINT: <log id or description>` to the desc so Cypra can
   dedup faster. Don't guess — only include if you actually know.

4. **Post ONE board item to `Cypra-PAA`** with this exact shape. Do NOT
   channel or /send — the board queue keeps intake organized.

   ```
   title:   Nightly billable notes: {client} — {date}
   session: Cypra-PAA
   status:  todo
   org:     (leave unset — Cypra-PAA has its own routing)
   desc:    [use the CLIENT/DATE/SOURCE/PROJECT/TASKS/TOTAL format below]
   ```

   Desc format (copy-paste and fill in):

   ```
   CLIENT: {client}
   DATE: {date}
   SOURCE_SESSION: {session}
   SOURCE_ITEM: <THIS item's board id — the nightly writeup task assigned to you>
   PROJECT_HINT: (Zoho Projects project name, or best guess)
   EXISTING_LOG_HINT: (only if you actually know a manual log already exists)

   TASKS:
   - [1.5h] <client-facing description>  (evidence: commit=abc1234)
   - [0.5h] <client-facing description>  (evidence: mtime=path/to/file, transcript="quoted line")
   - [2h]   <client-facing description>  (evidence: board=AH-42)

   TOTAL: <N>h provisional (Cypra will dedup against existing Zoho logs)

   Please PATCH the SOURCE_ITEM (my nightly writeup task, id above) with one
   of these outcome codes so I know how it was resolved:
     - `LOGGED — Zoho log ID <id>`                — hours logged in Zoho Projects
     - `STAGED — added to billing ledger backlog` — no Zoho project yet
     - `SKIPPED — duplicate of existing log <id>` — overlap detected
     - `NEEDS JEREMY INPUT — <reason>`            — needs human decision
   ```

5. **PATCH THIS ITEM to status=`doing`** (NOT done) with a short note:
   ```
   Posted to Cypra as <cypra-item-id>. Awaiting confirmation.
   ```

   Leave it in `doing` — Cypra will PATCH it to done with one of the four
   outcome codes above. This is what closes the loop. Do NOT self-close.

6. **On your next engagement, check this item's status:**
   - Still `doing`: Cypra hasn't processed yet. If >24h old, surface to
     Jeremy as pending ("Nightly writeup for {date} still awaiting Cypra
     confirmation").
   - `done` with `LOGGED — Zoho log ID X`: nothing further; billed.
   - `done` with `STAGED — ...`: nothing further; sitting in ledger backlog.
   - `done` with `SKIPPED — duplicate of existing log <id>`: nothing
     further; overlap correctly detected.
   - `done` with `NEEDS JEREMY INPUT — <reason>`: read the reason and
     surface to Jeremy on next engagement.

## If you did no billable work for {client} in the last 24 hours

This is the ONE case you self-close: PATCH this item to `done` with desc:
`No billable work today.` No need to post anything to Cypra.

## Rules

- **Provisional hours.** Your writeup is best-estimate + evidence; Cypra
  reconciles against existing Zoho logs. If in doubt, list the work — better
  Cypra dedups a duplicate than misses a real hour.
- **Evidence per item is required.** Without it Cypra cannot dedup and will
  bounce your submission back for detail. Commit hash / file mtime /
  transcript excerpt / board id — one of these per task, minimum.
- **Board items only.** Do NOT channel or /send Cypra — board keeps intake
  queued and prevents cross-agent interruption.
- **Client-facing language.** Skip AI/model/API-internals talk. Cypra
  renders these into Zoho Projects notes the client can read.
- **Round conservatively.** If you don't remember exactly, round UP to
  nearest 15 min per task.
- **Don't self-close.** Leaving your item in `doing` is what keeps it
  visible to Cypra — self-closing risks the item being pruned before Cypra
  reviews it.
"""


def main() -> int:
    today = date.today().isoformat()
    sessions = _cd_sessions()
    if not sessions:
        print("No CD-* sessions found — nothing to dispatch.")
        return 0

    posted = []
    errors = []
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
