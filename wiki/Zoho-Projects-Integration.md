# Zoho Projects integration (NWDDI <-> RTG mirror)

Four amux schedules (SCHED-338/339/340/341) and a set of scripts in a
separate repo. Owned by **Cypra-PAA**. Reviewed as AH-164, 2026-11-13.

## The recipe

Lives outside this repo at `/mnt/gitdata/Cypra/ops`
(remote: planned, not yet wired as of 2026-11-13). Read the README there
first — it is the authoritative recipe:

- The two-portal rule (NWDDI read-only, RTG writable).
- The join key (`NWDDI-RECORD-ID` marker in task descriptions).
- The intake gate (`zoho-intake-gate-draft` amux note).
- Every known Zoho API trap + the workaround.

Do not inline that content here. It drifts, and PAA is the only owner
of its truth.

## The four schedules

| ID | Cadence | Kind | Script | Dry run? |
|---|---|---|---|---|
| SCHED-338 | daily 15:40 UTC | shell | `nwddi_rtg_sync.py` | yes (`--live` NWDDI close is off until Jeremy approves) |
| SCHED-339 | daily 15:55 UTC | tmux | (PAA reads the newest report) | n/a |
| SCHED-340 | every 5 min | shell | `board_intake.py` | yes (no `--create`) |
| SCHED-341 | every 12h | shell | `idle_agent_ask.py` | yes (no `--send`) |

All three shell schedules wrap in `docker exec amux-org-Cypra` because a
bare host shell has no Zoho refresh token. SCHED-339 is kind=tmux because
the audit has to wake PAA (and costs LLM tokens on every fire — keep it
daily).

## Known substrate gaps

AH-164 review turned up two amux features that would simplify this
integration if added (filed as follow-up AH items by Cypra):

1. **Schedule `notify_on=error|always|never`.** Today `notify=0` is
   silent on both success and failure, and `notify=1` is chatty on both.
   The three shell schedules want silent-on-success, loud-on-failure.
   Near-term workaround: PAA's scripts wrap in a bash harness that posts
   a thread message to Jeremy on non-zero exit.
2. **Board `external_id` + unique index.** `board_intake.py` dedupes via
   a state JSON file + the `NWDDI-RECORD-ID` marker. A substrate-level
   external-id column would move the dedupe out of each script and
   survive state-file loss.

Not substrate gaps, but worth noting as future substrate options:

- A schedule field `container: <name>` that implicitly docker-execs in
  the named container. Would remove the hand-written wrap from every
  schedule command.
- Zoho Projects v3 webhooks could replace the 5-min poll in SCHED-340.
  Per-project scoping is finicky; the poll is adequate for now.

## Where to look when things break

- Reports: `/mnt/gitdata/Cypra/ops/state/*.json` (sync reports) and
  `/mnt/gitdata/Cypra/ops/state/board_intake_state.json` (dedupe).
- Schedule run history: `/api/schedules/<id>/runs` or query `schedule_runs`
  in the amux DB directly.
- `kind=shell` run failures are logged in `schedule_runs` with
  `status='error'` and the first 500 chars of stderr. Unless `notify=1`
  is set, that is the ONLY signal. See the near-term workaround above.
