#!/usr/bin/env python3
"""Board watchdog — replaces the AMUX-Watchdog agent that ran SCHED-38.

Procedure (deterministic; no LLM needed):
  1. List every non-discarded board item with a session assigned and status
     in (todo, doing).
  2. Group by assignee session.
  3. For each session that is API-status=idle AND has pending items: POST
     /api/sessions/<name>/send a nudge.
  4. Print a one-line summary per session (and a one-line total) to stdout —
     amux captures the first 500 chars of stdout into schedule_runs.note.

HARD RULES (mirror the prior agent's prompt):
  - Never claim, complete, PATCH, or change any board item.
  - Never start or stop sessions.
  - Only nudge sessions that are running AND API-status=idle. If the session
    isn't running or is mid-task, leave it alone.
"""

import json
import os
import ssl
import sys
import urllib.request

AMUX_URL = os.environ.get("AMUX_URL", "https://localhost:8822")
NUDGE_TEXT = "You have pending board items — check your board and pick up assigned work now."
# Only nudge for `todo` — items NOT yet claimed by anyone. `doing` means the
# agent has already claimed and is working or waiting on something external
# (a child task, a build, a peer); nudging there pesters an agent who is
# legitimately mid-task. (2026-06-29: Jeremy's call after agents complained.)
ACTIVE_STATUSES = {"todo"}

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _get(path: str):
    req = urllib.request.Request(AMUX_URL + path)
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def _post(path: str, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        AMUX_URL + path, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    try:
        board = _get("/api/board")
    except Exception as e:
        print(f"watchdog: failed to fetch board: {e}", file=sys.stderr)
        return 1
    try:
        sessions = _get("/api/sessions")
    except Exception as e:
        print(f"watchdog: failed to fetch sessions: {e}", file=sys.stderr)
        return 1

    # Build assignee → list[item_id] map (only active states)
    assigned: dict[str, list[str]] = {}
    for item in board:
        sess = (item.get("session") or "").strip()
        if not sess:
            continue
        if item.get("status") not in ACTIVE_STATUSES:
            continue
        assigned.setdefault(sess, []).append(item["id"])

    if not assigned:
        # No work outstanding — quiet success
        total = len(board)
        print(f"Board clear — checked {total} items.")
        return 0

    # Build session → state lookup. Only nudge sessions that are running AND
    # idle. The status field on /api/sessions reports "idle"/"active"/"waiting"/
    # "" (empty when not running).
    by_name = {s.get("name"): s for s in sessions}

    nudged = []
    skipped = []
    not_found = []

    for sess_name, ids in assigned.items():
        s = by_name.get(sess_name)
        if not s:
            not_found.append((sess_name, ids))
            continue
        # "running" presence: the API only includes running session names with
        # a non-empty status. We use status alone as the signal.
        status = (s.get("status") or "").strip()
        if status != "idle":
            skipped.append((sess_name, ids, status or "not-running"))
            continue
        try:
            _post(f"/api/sessions/{sess_name}/send", {"text": NUDGE_TEXT})
            nudged.append((sess_name, ids))
        except Exception as e:
            skipped.append((sess_name, ids, f"send-failed:{e}"))

    # One line per session for the schedule_runs.note (truncated by server at 500c)
    lines = []
    for n, ids in nudged:
        lines.append(f"{n}: nudged ({','.join(ids)})")
    for n, ids, why in skipped:
        lines.append(f"{n}: skip [{why}] ({','.join(ids)})")
    for n, ids in not_found:
        lines.append(f"{n}: not-found ({','.join(ids)})")
    summary = (
        f"Watchdog: {len(nudged)} nudged, {len(skipped)} skipped, "
        f"{len(not_found)} not-found. " + " | ".join(lines)
    )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
