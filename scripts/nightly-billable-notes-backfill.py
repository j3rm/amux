#!/usr/bin/env python3
"""
One-shot backfill dispatcher for a missed nightly billable window.

Reuses the machinery in nightly-billable-notes.py (session enumeration,
POST retry, task template) but pins the date and prefixes titles with
BACKFILL so agents and Cypra can distinguish these from the automated
nightly.

Cause of this specific backfill: on 07-03 morning I applied the
SCHED-44 stagger via SQL with `+1 day` on next_run, which silently
skipped the 07-03T23:32 window. Verified fixed for 07-04+ (see notes
on Cypra channel). This script recovers the 07-03 nightly by asking
each CD-* agent about 07-03 work now.

Run:
    python3 /home/jwesley/.amux/scripts/nightly-billable-notes-backfill.py 2026-07-03
"""
from __future__ import annotations
import sys
import importlib.util
from pathlib import Path


def _load_dispatcher_module():
    """Load the sibling nightly-billable-notes.py so we can reuse its bits
    without duplicating (session enum, POST retry with backoff, template)."""
    path = Path(__file__).parent / "nightly-billable-notes.py"
    spec = importlib.util.spec_from_file_location("nightly_billable_notes", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <YYYY-MM-DD>", file=sys.stderr)
        return 2
    backfill_date = sys.argv[1].strip()
    if not (len(backfill_date) == 10 and backfill_date[4] == "-" and backfill_date[7] == "-"):
        print(f"Invalid date {backfill_date!r} — expected YYYY-MM-DD", file=sys.stderr)
        return 2

    dispatcher = _load_dispatcher_module()
    sessions = dispatcher._cd_sessions()
    if not sessions:
        print("No CD-* sessions found — nothing to dispatch.")
        return 0

    posted = []
    errors = []
    for name, cfg in sessions:
        client = cfg.get("CC_DESC", "").split(" — ")[0].strip() or name.removeprefix("CD-")
        body = {
            # BACKFILL prefix + explicit date makes this trivially distinguishable
            # from the automated 07-04 nightly landing later tonight.
            "title": f"BACKFILL {backfill_date}: billable-notes writeup: {client}",
            "session": name,
            "status": "todo",
            "desc": (
                f"[ONE-OFF BACKFILL — missed automated nightly on {backfill_date} due to "
                f"a stagger-patch bug that silently skipped the 07-03T23:32 window "
                f"(see amux-helper channel with Cypra for full disclosure). "
                f"Cypra-PAA is reconciling and asked for this manual re-dispatch.]\n\n"
                + dispatcher.TASK_TEMPLATE.format(
                    date=backfill_date, client=client, session=name,
                )
            ),
        }
        try:
            item = dispatcher._post("/api/board", body)
            posted.append(f"{name}:{item.get('id')}")
        except Exception as e:
            errors.append(f"{name}:{type(e).__name__}")

    summary = (
        f"Backfill billable-notes dispatch {backfill_date}: "
        f"{len(posted)} posted, {len(errors)} errors. "
        + " ".join(posted[:20])
        + (f" ERRORS: {' '.join(errors)}" if errors else "")
    )
    print(summary)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
