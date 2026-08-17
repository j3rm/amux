# RESUME HERE — permanent amux-server.py worklog

**If you are Claude and you are about to edit `/mnt/gitdata/amux/amux-server.py`, this file is mandatory.** Every change must be planned here BEFORE you edit code. Completed plans stay in place as history — do NOT delete them. Read this file at the start of every session before touching amux-server.py.

Last updated: 2026-08-15

## Plan for change: dedup "session needs input" Pushovers (Jeremy 2026-08-17) — IN PROGRESS

**Trigger:** Jeremy. My AskUserQuestion prompt during the skill-hooks feature fired 5 spaced-out Pushovers while he took a minute to respond. He wants exactly one per waiting-cycle.

**Root cause (verified by reading L9434):**
```python
if status == "waiting" and prev in ("active", ""):
    ... _send_pushover ...
_session_prev_status[name] = status if running else ""
```
Transition-based fire — should be one-and-done. But two race conditions defeat it:
1. Status flap: pane rendering (spinner, tool output) can briefly read as `active`, so waiting → active → waiting counts as a fresh transition.
2. Running flap: if a tmux capture race reads `running=False` for one snapshot cycle, `prev` gets reset to `""` — next iteration with running=True + status=waiting matches `prev in ("active", "")` again and re-fires.

Either can happen multiple times per minute, hence Jeremy's 5 pings.

**Fix (belt + suspenders, ~8 lines):**
Add per-session cooldown on top of the transition detection.
- Module-level dict `_wait_pushover_last: dict[str, float]` (name → epoch of last fire).
- Constant `_WAIT_PUSHOVER_COOLDOWN_S = 600` (10 min — comfortable margin over any legit user-response window; if Jeremy hasn't responded in 10 min a re-ping is reasonable).
- Inside the fire branch: skip if `time.time() - _wait_pushover_last.get(name, 0) < _WAIT_PUSHOVER_COOLDOWN_S`. On fire, stamp `_wait_pushover_last[name] = now`.
- When status leaves waiting (goes idle/active): pop the timestamp so the NEXT waiting-cycle after Jeremy answered gets a fresh Pushover immediately (not blocked by the 10-min cooldown from the prior cycle).

**Explicitly NOT doing:**
- Not making the cooldown configurable via env — one universal value is simpler, and Jeremy can adjust the constant if needed.
- Not touching the underlying transition check — leave it as belt AND add cooldown as suspenders. Both firing conditions must be met.
- Not adding cooldowns to other Pushover paths (auto-restart, context-exhausted, etc.) — those are already mostly one-shot per real event and Jeremy hasn't reported dupes there.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`.
2. `touch amux-server.py` → hot-reload.
3. Sanity: any waiting session that flaps status/running should get exactly one Pushover per unique waiting-cycle.
4. If Jeremy sees dupes again, we add slog on suppression and re-diagnose.

---

## Plan for change: creator-notify on completion (Jeremy 2026-08-17) — IN PROGRESS

**Trigger:** Jeremy. When agent-A creates a task assigned to agent-B, and agent-B completes it, agent-A currently gets nothing. Requested a completion-push analogous to the existing assignee-notify.

**What already works (surveyed L6520-L6600, L42918):**
- Fields `creator` + `session` + `owner_type` all present on issues.
- Helper `_notify_session_of_task` (L6520) — tmux inject via `send_text`, atomic idempotent via a `notified` DB flag, best-effort background thread.
- Siblings `_notify_session_of_retake` (L6560) + `_notify_session_of_verified` (L6586) — for C3/C4 cascades.
- PATCH handler at L42918 already has the exact hook site: after auto-assignee-notify block, before C3/C4 cascade.
- Migration pattern for new DB columns: append ALTER to the loop at L5821 (try/except per stmt, ignore "column exists").

**Fix (four small pieces):**

1. **Schema migration**: `ALTER TABLE issues ADD COLUMN creator_notified INTEGER NOT NULL DEFAULT 0`. Wrapped in the existing try/except loop.

2. **Helper `_is_real_session(name)`**: returns `bool(name and (CC_SESSIONS / f"{name}.env").is_file())`. Prevents notify attempts against `""` / `"Jeremy"` / any non-session creator value (Jeremy chose NOT to Pushover on creator=Jeremy; just skip).

3. **Helper `_notify_creator_of_completion(creator, item_id, title, new_status, closer, note_first_100)`**: mirrors `_notify_session_of_task`. Message shape:
   `"Completed: {item_id} — {title[:80]} → {new_status} by {closer}. Note: {note[:100]}. See `amux board show {item_id}` for detail."`
   Atomic idempotent via `creator_notified` DB flag (0→1 CAS). Best-effort background thread. Clears the flag on send-failure so a session restart still gets the ping.

4. **Wire into PATCH handler** at L42918, right after the auto-assignee-notify block. Conditions (per Jeremy 2026-08-17):
   - `new_status ∈ {done, verified, discarded}` AND `prior_status ∉ {done, verified, discarded}` (only fire on the FIRST transition into terminal state)
   - `creator != closer` (skip self-close — noise; Jeremy chose this)
   - `_is_real_session(creator)` (skip empty / Jeremy / unknown)
   - Note payload extracted from PATCH body's `desc` field (Jeremy chose to include the closer's note in the ping)

**Explicitly NOT doing:**
- No Pushover-to-Jeremy fallback when creator is Jeremy (Jeremy explicitly chose skip).
- No new notify for status transitions between non-terminal states (todo→doing etc.) — completion only.
- No re-notify on subsequent state churn — first transition to terminal wins; `creator_notified` flag ensures at-most-once.
- No dashboard UI change — this is agent-facing infrastructure.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload (auto-migrates the new column on startup).
3. Sanity: post a test board item from amux-helper session to another running session; peek that session; PATCH to done from the assignee side; peek amux-helper's session for the completion nudge.
4. Confirm no double-fire on subsequent PATCHes.

---

## Plan for change: reject empty command on POST /api/schedules (AH-60, 2026-08-16) — IN PROGRESS

**Trigger:** AH-60 from RTG-Research. SCHED-225 (once, kind=tmux, session=RTG-Research) fired at 20:22:18 on 2026-08-15 with status=ok and run_count=1 — but no wakeup visibly arrived, and RTG-Research's in-flight watch stayed orphaned for hours.

**Root cause (verified by reading the DB record, not guessed):**
- SCHED-225's `command` field is the empty string `""`.
- Schedule was armed at 20:22:16 with `run_at=2026-08-15T20:22` (client sent `run_at=now`, not `now+30m` as they intended — a client arithmetic bug).
- Scheduler fired at 20:22:18 (2s later), called `send_text("RTG-Research", "")`. `send_text` accepts empty text (line 11744 has no guard) and returns success. status=ok logged.
- Nothing actually appeared in RTG-Research's tmux pane, because we sent zero bytes.

**Fix (one place, tight scope):**

POST /api/schedules at L43016-L43070: reject with HTTP 400 when `kind ∈ {"tmux","shell"}` AND `data.get("command","").strip() == ""`. Applies only to kinds that dispatch a payload — event-triggered / notify-only kinds (if any) unaffected. Message includes the exact reason so a future agent debugging the same shape sees it at post time, not hours later via an orphaned watch.

**Explicitly NOT doing:**
- Not changing send_text() to reject empty text — an empty send is legitimate at the tmux layer (e.g. "just hit Enter"). The problem is silent-scheduling with no payload, not the send primitive.
- Not adding a "run_at is in the past" guard — legitimate use cases exist (run-immediately at POST time).
- Not adding a "delay_minutes" convenience field — that's a separate feature request. Client can compute the timestamp itself; the empty-command bug is the concrete failure to fix.
- Not touching PATCH /api/schedules/<id> — same guard could apply but is out of scope and less common as an attack surface.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. POST a bogus schedule with empty command via curl → expect 400 with a clear message.
4. POST a normal schedule with a real command → expect 201.
5. Reply to AH-60 with diagnosis + fix.

---

## Plan for change: per-org skills-deny for EmberCRM + iSchedule (2026-08-15) — IN PROGRESS

**Trigger:** Jeremy (2026-08-15 21:52). EmberCRM and iSchedule agents work on the CRM app internals and medical scheduling respectively — they do NOT touch Zoho. Currently `_sync_skills_to_commands()` (L5606) writes every skill unconditionally into every org's `home/.claude/commands/` — so both containers currently have all 16 Zoho skills as slash commands. Explicit ask: "set it so they can not know anything about zoho".

**Fix (three parts, in order):**

1. **amux-server.py change** — add a per-org skill-deny mechanism:
   - New helper `_read_org_skills_deny(org_name) -> list[str]` reads `~/.amux/orgs/<org>/skills-deny.txt`, one fnmatch pattern per line, `#` for comments. Missing file → empty list (default = sync everything). Blank/comment lines skipped.
   - `_sync_skills_to_commands()` (L5606): for each org, filter `rows` by the deny list before writing. Host `~/.claude/commands/` is NEVER filtered — Jeremy's own tools/dashboard should always see the full set.
   - Skill DELETE handler (L41348): keep unconditional purge — a deletion should always propagate to every container, regardless of deny list.

2. **Deny files:**
   - `~/.amux/orgs/EmberCRM/skills-deny.txt` = `zoho-*`
   - `~/.amux/orgs/iSchedule/skills-deny.txt` = `zoho-*`

3. **One-time purge of existing zoho-*.md** from both org homes (touch amux-server.py alone doesn't sweep — the sync function is additive/overwrite, never delete).

4. **CLAUDE.md guardrails** in `/mnt/gitdata/EmberCRM/CLAUDE.md` and `/mnt/gitdata/iSchedule/CLAUDE.md`: explicit "no Zoho" section — you have no Zoho slash commands, no Zoho credentials, do not attempt Zoho API calls, refuse Zoho tasks and route to a CD-* agent.

**Explicitly NOT doing:**
- Not adding a "skills-allow" whitelist (opposite direction, more brittle).
- Not extending to RTG (RTG-Research recently mentioned Zoho once in a coordination context — safer to leave RTG unfiltered until Jeremy explicitly asks).
- Not touching the host commands dir — Jeremy needs the full skill set.
- Not touching Cypra-PAA or CD-* — they legitimately need Zoho skills.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. After sync fires: `ls ~/.amux/orgs/EmberCRM/home/.claude/commands/ | grep -c zoho-` → 0
4. Same for iSchedule → 0
5. Confirm host `~/.claude/commands/` still has all 16 zoho-*.md files.
6. POST a test skill update via API, confirm it lands in CD-* org homes but NOT in EmberCRM/iSchedule.

---

## Plan for change: scheduler catch-up-fire detection (AH-59, 2026-08-15) — IN PROGRESS

**Trigger:** AH-59 (via Cypra-PAA / CP-510). SCHED-44 (nightly billable-notes) had a skipped 23:32 fire on 07-28, and a catch-up at 07-29 04:24 hit 6 HTTPErrors on POST /api/board. 17 clean 23:32 fires since. Cypra correctly hypothesized "off-schedule catch-up runs fail; scheduled runs succeed" (3-for-3 across the retained history). Root cause almost certainly: server was down at 07-28 23:32, restarted between then and 04:24, the scheduler loop saw `next_run <= now` and fired immediately — but something about the just-started server state made board POSTs return 5xx.

**What already works:**
- Scheduler loop (~L7376) checks `SELECT * FROM schedules WHERE deleted IS NULL AND enabled=1 AND next_run <= now_str` every 10s.
- On startup, any schedule whose next_run is in the past fires immediately. There's no "recent enough" filter, so a schedule that missed its slot during downtime gets caught up.
- After firing, `next_run` is advanced to the next cron match (line 7414-7417). No double-fire risk.

**Failure mode (theorized, not fully re-repro'd because runs table only retains 20 rows and the 07-28/07-29 rows are aged out):**
Server restart / hibernation / execv reload leaves the process ready enough to accept HTTP but the scheduler tick runs before all board-writer dependencies (or a concurrent restart-driven contender for the SQLite write lock) settles. The dispatched script's POSTs 5xx, only the exception class is recorded, and the failure is invisible until SCHED-45's 08:32 silence audit catches it 8h later.

**Fix scope (this change):**
Add ONE slog line: when `_run_schedule` is about to fire, compare `next_run` to now. If it's >30 min in the past, emit `slog("[sched] CATCH-UP fire: '{title}' next_run was {delta_min}m ago (server likely restarted since scheduled slot)")`. This gives us the correlation on the NEXT incident — no more "why did this fire at 04:24?".

**Explicitly NOT doing in this change:**
- Not blocking catch-up fires (they can be legitimate — e.g. deploy that took 90s to restart shouldn't drop that night's dispatch).
- Not adding a "grace period skip" — too easy to accidentally drop a legit run.
- Not touching the script-side error capture or Pushover-on-0-posted — those are done in-place at /home/jwesley/.amux/scripts/nightly-billable-notes.py (no amux-server.py change needed).

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` (auto-reload).
3. Grep server.log after next server restart: any schedule that missed its slot during downtime should emit a `CATCH-UP fire` line.
4. On the next real incident (SCHED-44 or any other), the log will show whether the errors were on a catch-up (theory confirmed) or a normal fire (new failure mode to hunt).

---

## Plan for change: escalation-dedup gate allows a new ESC after prior closes (2026-08-14) — IN PROGRESS

**Trigger:** Ember-Research board escalation (first confirmed occurrence, ~1h silent stall overnight). Sequence: EAAC-18 round-1 split → ER-326 minted → adjudicated FAIL → re-take → round-2 audits closed with ANOTHER split (EAO-195 PASS vs EAC-218 FAIL) → C4 tried to mint a fresh ESC → the 24h dedup gate blocked it because ER-326 still exists → item stuck silently in review. Ember-Research's night-keeper caught it manually and self-minted ER-327 (which worked).

**Root cause (verified by reading the code, not guessed):**
- Two identical dedup gates exist:
  - Internal auto-mint path: `_auto_mint_escalation` at ~L8743-8752
  - POST board-item explicit-mint path: ~L42450-8
- Both key on `(target_id in title) AND created < 24h ago AND status != 'discarded'`.
- **Failure mode:** the check only excludes `discarded`. If a prior ESC closed cleanly with `done` or `verified`, the check STILL matches it — and blocks any new escalation for the target for 24h, even though the prior adjudication is completed.
- Ember-Research's ask: *"a closed adjudication should not block the next round's escalation"* — exactly correct read of the gate.

**Fix (one-line change in each of two places, symmetric):**

Change `AND status != 'discarded'` → `AND status NOT IN ('discarded', 'done', 'verified')` in both dedup queries.

Result: the gate still blocks concurrent double-mints (prior ESC in flight = still open in todo/doing/review) but allows a fresh mint once the prior adjudication is complete. That's the exact semantics Ember-Research requested.

**Why not the alternative "key on (target + round)" approach they mentioned:**
- Round number isn't in the schema. It'd have to be inferred from the count of prior audit pairs on the target — real work, more surface area for bugs.
- The closed-status fix covers the same failure mode with proven safety: it can't false-positive because CLOSED means adjudicated, and adjudicated means "this round is finished, next round's escalation is a fresh event".
- The 24h cooldown's original purpose was preventing double-mint from a hook edge case / concurrent audit patches. That purpose is preserved — if the prior ESC hasn't closed yet, the gate still blocks.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`.
2. `touch amux-server.py` → PID-preserved hot-reload (per SESSION-RESTART CHAIN rules).
3. Reply to Ember-Research via board item when done.
4. Grep server.log for future `escalation-gate: 24h cooldown` blocks — should now only show on legitimately concurrent mints.

**NOT doing:**
- No change to the escalation-mint logic itself, C3/C4 flip logic, or the retake/verified nudges (all recent additions still work).
- No schema change.
- Not adding a round counter.
- Not touching the "settled target" or "VOID" gates — different checks, different concerns.

---


## Plan for change: C3/C4 nudge owning session on flip to `verified` (2026-08-13) — IN PROGRESS

**Trigger:** Ember-Research board escalation (third confirmed occurrence): the audit-pair hook (C4) and the adjudication hook (C3) auto-flip a worker item to `verified`, but the item's owning session is never notified. Workers idle at "waiting for audit results" until manually nudged. Documented cases today: EA-11 (~02:00 UTC, Ember_Auth idle 10+ min post-verify), EA-12 (~13:10 UTC, same), EA-10 chain (~01:00 UTC, related shape). Current workaround: Ember-Research fires SCHED-130/146 one-off tmux schedules into the owner pane manually.

**What already exists (surveyed, not guessed):**
- `_notify_session_of_retake` (~L6506) — helper that pushes a nudge into the target session's tmux pane when a FAIL adjudication (C3) or FAIL/FAIL audit pair (C4) flips a target back to `doing`. Uses `send_text()`, background thread, best-effort.
- Call site in C3 (`_auto_apply_verdict_from_rr`, ~L8822): fires the retake nudge when `new_status == "doing"`.
- Call site in C4 (`_auto_verify_from_audit_pair`, ~L8919): same, fires when `new_status == "doing"`.
- **Gap:** neither branch has a mirror for `new_status == "verified"`. That's the reported bug.

**Fix (symmetric addition, minimal):**
1. Add a sibling helper `_notify_session_of_verified` right next to `_notify_session_of_retake`, same shape (session, item_id, title, verdict, source_id, source), same background-thread + `send_text` mechanism, log tag `[verified-nudge]`. Text tells the owner the item flipped to verified and to proceed with any post-verification step in their instructions — neutral, informational, not directive.
2. Two-line addition in each of the two verdict-apply seams:
   - C3 (`_auto_apply_verdict_from_rr`, ~L8821): after the existing `if new_status == "doing"` retake branch, add an `elif new_status == "verified" and target["session"]:` calling the new helper.
   - C4 (`_auto_verify_from_audit_pair`, ~L8919): same elif branch after the FAIL/FAIL retake block.

**Why this is safe:**
- `send_text` already handles the recipient being restarted, at a resume picker, at a shell prompt, etc. — it auto-wakes and delivers. Established mechanism, used everywhere already.
- Best-effort background thread, exceptions swallowed — a failed nudge cannot fail the verdict-application itself.
- The nudge text is informational, not directive. Workers already know to check their board queue; this just kicks their event loop.
- No schema changes, no new API endpoints, no new state to persist.
- Zero effect on FAIL paths (they still fire the existing retake nudge unchanged).

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`.
2. `touch amux-server.py` → PID-preserved hot-reload (SESSION-RESTART CHAIN rules).
3. Grep server.log for `[verified-nudge]` after the next real audit pair closes with a PASS/PASS.
4. Once seen live, reply to Ember-Research on the board.

**NOT doing:**
- No change to the C3/C4 flip logic itself, the verdict extractor, or the audit-pair matching.
- No change to `_notify_session_of_retake` — new helper alongside, not a rename.
- No change to the SPLIT-verdict escalation path.
- Skipping the "check `notified` flag on the target" pattern used elsewhere for fresh-mint suppression — this is a post-verify signal for the OWNER, not a mint, and firing more than once (edge case if the flip somehow re-triggers) is harmless.

---


## Why this file exists (permanent rule — Jeremy 2026-08-07)

> "It took way too long and too many resets for us to finally get traction
> on what we were trying to fix here because we can't be losing context in
> the middle of it. I want you to continue to use that through every and
> any changes that we make to the python script. Because it takes way too
> long for me to re-explain to you what the hell you were doing. This is
> not going away. This is fundamentally how you will be moving forward."

The amux server watches its own mtime and restarts on save. Historically
(pre-`277855c`) that restart chain wiped every agent session on every edit,
killing multi-hour investigations mid-flight. The `277855c` fix means edits
no longer kill sessions, but manual restarts, systemd interventions, and
unexpected regressions can still reset context. **This file is the only
thing that survives every kind of reset.**

## How to use this file

1. **Session start:** read this file end-to-end before touching
   `amux-server.py`.
2. **Before an edit:** append a new `## Plan for change: <slug>` section
   with:
   - what you intend to change
   - why (bug being fixed / feature being added, with the trigger — bug
     report, Jeremy request, log excerpt)
   - expected observable behavior after the change
   - verification steps (concrete commands, expected outputs)
3. **After landing the change:** update your plan section with the commit
   hash and the verification result. Do NOT delete it. It becomes worklog
   history for the next Claude that hits related code.
4. **Only prune** truly stale sections (weeks old, no ongoing relevance),
   and only after moving durable ops knowledge to `wiki/`.

## Companion memories / rules
- Project [`CLAUDE.md`](CLAUDE.md) "Workflow" section carries the same rule.
- Auto-memory: `feedback_log_before_server_edit.md` (loaded via
  `MEMORY.md` index).

## 🔒 LOCKED-IN FIXES — do not regress

Working code that took real effort to land. Grep for the tag before
editing the surrounding area:
- **`/login` OAuth flow** (2026-08-07): two-part fix, both essential.
  - Pane linkifier: `ansiToHtml.linkChunk` (~L23222). Multi-line URL
    regex. NOT `linkifyOutput` — that's message bodies only.
    Verbose warning banner in the code.
  - Server-side prefix strip: `/send` handler `[oauth-strip]` block
    (~L45494). Peeks pane, strips `[HH:MM AM]` when Claude Code's
    "Paste code here" prompt is visible. Authoritative fix; the
    client-side `_pendingLogin` flag in `doSend` is belt-and-
    suspenders only.
  - Full history in the "Plan for change: fix linkifier + server-side
    OAuth prefix strip" section below. Landed in commits `6d19314`,
    `5624b97`, `9c2aed0` (comment lock-in).

---

## Environment (verified 2026-08-07 03:55 UTC)

Two independent restart mechanisms exist and interact badly:

### 1. amux-server.py's in-process mtime watcher
`_watch_self()` at L46836. Runs in a **daemon thread**. When mtime changes:
1. Log `"amux-server.py changed — debouncing 3s..."`
2. Debounce loop until settled
3. Log `"settled — restarting"`
4. Validate syntax
5. **Call `server.shutdown()` on a helper thread** (this is the bug — see next section)
6. `server.socket.close()`, `server.server_close()`
7. `time.sleep(0.5)`
8. `os.execv(sys.executable, [sys.executable] + sys.argv)` ← INTENDED path

### 2. systemd `amux.service` (~/.config/systemd/user/amux.service)
- `Type=simple`, `Restart=always`, `RestartSec=10`
- `KillMode` defaults to `control-group` — **when the main PID exits, systemd kills every process in the service cgroup**, including all `tmux new-session` children (i.e. every agent session).
- `StandardOutput=append:~/.amux/logs/server.log`

### Other watchers/services touching amux
- `amux-perf.service` (user) — runs `scripts/perf-monitor.py` every 30s, writes `~/.amux/logs/perf.jsonl` + `perf-monitor.err`. **Read-only** from amux-server's POV; does not touch amux-server.py.
- `amux-serve.service` (system, `/etc/systemd/system/`) — legacy: `tmux new-session -d -s amux 'amux serve'`. Read; does not modify amux-server.py.
- `amux-projects.service` (system, oneshot) — runs `/home/jwesley/start-projects.sh`. Read.
- `scripts/watchdog.py` — invoked by a **scheduler entry inside amux itself**, not systemd. Only nudges idle sessions with pending board items; does not touch amux-server.py.
- `~/.claude/hooks/` — nothing that touches amux-server.py (grep verified empty).

Log locations (know these — do not invent new ones):
- `~/.amux/logs/server.log` — systemd stdout+stderr; contains all `slog()` output. Grep here first.
- `~/.amux/logs/perf.jsonl` — sampled every 30s. Useful for diagnosing memory/CPU spikes correlated with restarts.
- `~/.amux/logs/perf-monitor.err` — perf-monitor.py errors.
- `~/.amux/logs/<session-name>.log` — per-session pane capture, piped through a secret-redaction filter (see the giant `sh -c` you'll see under the amux.service cgroup).
- `journalctl --user -u amux.service` — systemd view of restarts (`Scheduled restart job, restart counter is at N`).

---

## The overarching problem — REAL root cause (identified 2026-08-07 04:00)

**`os.execv` in `_watch_self()` never runs.** Chain:

1. Someone edits `amux-server.py` (any change to mtime, even `touch`).
2. Watcher thread detects, debounces 3s, logs `"settled — restarting"`.
3. Watcher spawns a helper thread that calls `server.shutdown()`.
4. `server.shutdown()` signals the main thread's `serve_forever()` (L47269) to return.
5. Main thread returns from `serve_forever`, falls through the `except KeyboardInterrupt` block (no exception, so nothing runs), and **exits Python normally with code 0**.
6. All non-main threads are `daemon=True`, so the watcher thread is killed the moment the main thread returns. **`os.execv` never executes.**
7. Process exits with code 0. systemd sees clean exit.
8. `KillMode=control-group` (default) → systemd kills every process in the amux.service cgroup, including every agent's `tmux new-session` child. **This is what kills Claude sessions mid-conversation.**
9. `RestartSec=10` → systemd starts a fresh amux-server.py 10 seconds later.
10. New amux-server startup calls `_maybe_restart_session` / equivalents → relaunches every crashed session → `start_count` increments.

**Evidence supporting this diagnosis:**
- `os.execv` preserves PID on this host (verified with a 10-line test script → parent and child both pid=1668254).
- Current running amux-server pid=753941, PPID=1077 (systemd --user), NOT self-inherited. If execv had worked, PPID would still be systemd but PID would have been continuous across restarts. Instead every restart in `server.log` shows a NEW pid in the next heartbeat line.
- `systemctl --user show amux.service`: `ExecMainCode=0 ExecMainStatus=0 Result=success NRestarts=10` — the process is exiting cleanly, not crashing.
- systemd journal: `"Scheduled restart job, restart counter is at 10"` at 10-second intervals after each `[restart] settled — restarting` line.
- `amux-helper.meta.json` `start_count` climbed from 14 → 16 during this session with no manual edits by me, matching the pattern of external mtime changes triggering the loop.

### Why the AH-55 PID guard didn't help
AH-55 protects against amux's OWN `respawn-pane -k` code path (inside `start_session`). But the killer here is systemd's `KillMode=control-group`, which fires OUTSIDE amux entirely. No amux-internal guard can prevent this.

### Who is touching amux-server.py?
Not this session (I did not edit before this line). Suspects (unverified, next-step to investigate):
- Another agent session editing amux-server.py concurrently (grep transcripts for edits).
- A hook or scheduled job doing `touch amux-server.py` (nothing found in `.claude/hooks/`, but not exhaustive).
- A backup/rsync process resetting atime/mtime (unlikely — only mtime triggers the watcher; rsync typically preserves mtime, not resets it).
- The mtime observed at 03:45:36 lines up with the previous session's activity window. Might be genuine legitimate edits from another concurrent claude session.

The point is: **the mtime trigger is not the bug**. The bug is that the "restart" path exits the process instead of exec-ing it, letting systemd + KillMode take down every session.

---

## Plan for change: session-restart bug (2026-08-07) — DONE ✅

**Summary:** Every mtime change to `amux-server.py` was killing every agent
session on the box. Root cause: `_watch_self` called `server.shutdown()`
before `os.execv`, main thread exited Python cleanly, daemon watcher died
before execv could run, systemd saw a clean exit, `KillMode=control-group`
slaughtered the cgroup including every tmux child.

**Landed commits (in order):**
- `277855c` — `fix(watcher): direct os.execv in _watch_self — stop nuking agent sessions`
- `a307405` — `fix(watchdog): rehydrate hibernation flag from disk on restart`
- `a84ace6` — `fix(watchdog): AH-56 PID cross-check before auto-restart in _snapshot_all_sessions_inner`
- `2cf0807` — `fix(sessions): AH-55 PID guard in start_session — never respawn-pane -k a live claude`
- `a39e9d6` — `fix(cli): board add — omit creator (server now handles the notify-guard)`

**Verified 2026-08-07 11:20 UTC:** `touch amux-server.py` after `277855c`
loaded → PID **1697930 preserved** across the mtime change, systemd
`NRestarts` unchanged at 13, log showed
`[restart] pid=1697930 direct execv → …` followed by
`[startup] pid=1697930`, dashboard responded HTTP 200. Fix works.

**Follow-up investigation retained below** — kept for future Claude that
touches `_watch_self`, `_snapshot_all_sessions_inner`, `start_session`,
or debugs a new session-restart pattern.

### Step 1 — add better logging to `_watch_self` — DONE ✅ (2026-08-07 ~11:01 UTC)
Instrumentation confirmed the hypothesis. Restart at `2026-08-07 11:01:12`
produced exactly ONE diagnostic line before the process died:

```
[restart] amux-server.py settled — restarting (uptime=25041s, requests=1550, threads=10)
[restart] pid=2010987 calling server.shutdown() on helper thread
   ← nothing more from this pid
```

`server.shutdown()` unblocks `serve_forever()` in the main thread → main
thread exits Python cleanly → daemon watcher thread dies before it can
reach `os.execv`. systemd sees the clean exit and (default
`KillMode=control-group`) kills every process in the amux.service cgroup,
including every agent's `tmux new-session` child.

### Step 2 — fix the exit-before-execv bug — DONE ✅ commit `277855c`, verified `touch` 11:20 UTC preserved PID 1697930 and NRestarts=13

**Status:** The fix is already in the working tree at
`amux-server.py:46836–46893` (uncommitted). It has NOT yet been verified —
we have not deliberately triggered a restart post-fix and confirmed the
PID stays the same.

The applied code path in `_watch_self` after the syntax check:

```python
slog(f"[restart] pid={os.getpid()} direct execv → {sys.executable} {sys.argv}")
sys.stdout.flush()
sys.stderr.flush()
try:
    os.execv(sys.executable, [sys.executable] + sys.argv)
except OSError as _execv_err:
    slog(f"[restart] execv FAILED: {_execv_err!r}")
    raise
```

No `server.shutdown()`, no `server.socket.close()`, no `server.server_close()`,
no `time.sleep(0.5)`. `os.execv` replaces the process image directly; the
kernel closes all fds (including the listening socket) and PID is preserved.

**Bonus change also in working tree (AH-56, NOT in the original plan):**
`_snapshot_all_sessions_inner` at ~L4098 now cross-checks
`_find_claude_pid(name) <= 1` before auto-restarting on the `_at_shell_prompt`
text heuristic. Rationale: the text heuristic can false-positive right after
an amux-server execv (pane state momentarily desynced). A live claude PID
is authoritative — skip the restart if a claude child is still there. This
is a second, independent safety net; if the Step 2 execv fix works
perfectly, this guard should never actually fire, but it prevents the same
session-wipe outcome via the auto-restart path if anything else desyncs the
pane state.

**Expected effects of Step 2:**
- PID stays the same across every save → systemd sees no exit →
  `Restart=always` does NOT fire → no `KillMode=control-group` slaughter of
  agent sessions.
- The 10-second `RestartSec` downtime window disappears.
- AH-55 PID guard (L10623) reverts to belt-and-suspenders — keep it.

### Step 2 verification — DONE ✅ 11:20 UTC (results below preserved as diagnostic reference)

**Commit `277855c` landed** — `_watch_self` fix committed in isolation
(no other hunks bundled in). Working-tree mtime was unchanged after the
commit, so the running (still-OLD-code) server has not yet fired.

**The running amux-server (BEFORE snapshot):**
- PID = 1697930
- systemd `NRestarts` = 13
- Started 2026-08-07 11:07:18 UTC

**About to run:** `touch amux-server.py` — this will bump mtime and
provoke the OLD (buggy) watcher one last time. Expected chain:
1. Old `server.shutdown()` path runs → process exits clean.
2. systemd sees clean exit, `KillMode=control-group` slaughters the
   cgroup → THIS SESSION DIES.
3. `RestartSec=10` → new amux-server starts ~10s later.
4. New process has the NEW `_watch_self` in memory.
5. Any future edit will use `os.execv` → PID preserved → no more kills.

**If you are the fresh Claude reading this after that restart:**
- The running amux-server should be a NEW PID (not 1697930), started
  around 11:18-ish UTC. `NRestarts` should be **14** (up by exactly 1).
- To VERIFY THE FIX now works: `touch amux-server.py` again. This time:
  - PID should stay the same.
  - `NRestarts` should stay at 14 (not go to 15).
  - `~/.amux/logs/server.log` should show `[restart] pid=X direct execv → …`
    followed by a `[startup]` from the SAME pid X.
  - No new `Scheduled restart job` in
    `journalctl --user -u amux.service --since "5 minutes ago"`.
- If that verification passes → mark task #2 done, move to task #3
  (commit remaining hunks separately), then task #4 (delete plan
  section here).

**If verification FAILS after the restart:** do NOT retry the same fix.
Read the new diagnostic slog lines (execv FAILED? or execv succeeded
but a different path is exiting the process?). Update THIS file with
what the log actually showed, then diagnose. Root causes still to
consider if execv is not the whole story:
  - Some other thread calling `sys.exit()` or raising unhandled on file
    change (grep for `sys.exit`, `os._exit`, `SIGTERM` handlers).
  - `systemd` also watches something else (e.g. a `PathModified=` unit
    could be lurking).
  - The `.service` file might be configured with an `ExecStopPost` we
    haven't inspected.

**Uncommitted hunks still in the working tree** (do NOT lose these
across the restart — they persist because they're on disk):
- `_snapshot_all_sessions_inner` hibernation rehydrate (~L3959)
- `_snapshot_all_sessions_inner` AH-56 PID cross-check (~L4098)
- `start_session` AH-55 belt-and-suspenders (~L10623)
- `amux` CLI — drops `creator` from board add payload
Backup patch files saved at:
`/tmp/claude-1000/-mnt-gitdata-amux/d9dda1be-59be-4821-b9a6-f825df1cde1d/scratchpad/amux-server.full.patch`
`/tmp/claude-1000/-mnt-gitdata-amux/d9dda1be-59be-4821-b9a6-f825df1cde1d/scratchpad/amux-cli.patch`
(These are in /tmp which is ephemeral — do NOT rely on them
surviving a host reboot; they survive session restart only.)

### Step 3 — DONE ✅ (2026-08-07 11:30 UTC) — all remaining hunks committed as separate one-task-per-commit changes: `a307405`, `a84ace6`, `2cf0807`, `a39e9d6`. See "Landed commits" list above.

### Step 4 — this file itself — DONE ✅ (2026-08-07 13:30 UTC)
Restructured RESUME-HERE.md from a one-off "resume the investigation"
doc into the permanent worklog Jeremy now requires. Completed plan
sections stay in place as history (do NOT delete). Header, "How to use
this file" preamble, and companion memory pointers added.

---

## Previously-identified bugs (still relevant context)

### Bug A — `send_text` corrupted messages ≤400 chars
Previous code used `send-keys -l` for short text, which typed char-by-char through the PTY. Some chars in URL-safe payloads hit unrelated Ink TUI keybindings, silently corrupting the payload. **First bug we chased. Believed fixed** by the paste-buffer rewrite in the uncommitted diff (L11549+). Has a `/login`-modal detection branch that skips bracketed-paste markers, because Anthropic's OAuth code prompt is readline-style and would submit the `\e[200~ … \e[201~` verbatim.

### Bug B (AH-55) — `start_session` respawn-pane -k on live Claudes
Uncommitted PID-guard at ~L10628. Still valid protection against amux's own `respawn-pane -k` at L10985. Keep it — but note it doesn't address the systemd-KillMode chain above.

---

---

## Plan for change: PATCH /api/messages supports `blocking` field (2026-08-11) — IN PROGRESS

**Trigger (Jeremy 14:03 PT):** T-147 has `[BLOCKING]` on it, never cleared. The agent said it can't clear. Confirmed: the PATCH `/api/messages/M-N` handler at ~L40717 handles `read`, `flagged`, `body`, `discarded` — but has NO code path for `blocking`. Agents can't clear it because the API silently ignores the field.

The offending message is M-2727 (Jeremy's own, `blocking=1, status=complete`). The thread's `anyBlocking` badge (~L29068) is `some(m => m.blocking === 1 && m.status !== 'discarded')` — so a persistent blocking-flag on any message stamps the whole thread.

**Two fixes, one commit:**

1. **Clear M-2727 blocking now** via direct SQL — one-shot data fix, keeps the message content intact.
2. **Add `blocking` to PATCH /api/messages/M-N** — same shape as `read` and `flagged`: `if "blocking" in bj: UPDATE messages SET blocking = ?, updated = ? WHERE id = ?`. Then `amux threads` CLI or any agent can `PATCH {"blocking": false}` on a message they've addressed.

**Auth story (no new gate needed):** the existing thread org-isolation from `d25707b` / `01c81fd` already prevents cross-org and agent-to-agent thread posts. Any agent that CAN read the message via the existing rules should be able to flip `blocking` on it — same as they can flip `read`. Jeremy (dashboard UI token) always bypasses org checks so he can clear anything.

**NOT doing:**
- No new dashboard UI. The blocking checkbox on the compose modal already sets it; a clear-blocking action can be added later if useful, but for now `amux threads` CLI + API is enough.
- No changes to the SSE / delivery path — clearing blocking after delivery doesn't re-deliver anything.

**Verification:**
1. Syntax check + hot-reload preserves PID.
2. Curl PATCH `/api/messages/M-2727` with `{"blocking": false}` as an agent → 200, blocking=0.
3. GET T-147 → `anyBlocking` computes to false (no `[BLOCKING]` badge in UI).

---

## Plan for change: bare `GET /api/sessions/<name>` 404 + REMOTE session marker (2026-08-07) — DONE ✅ commit `e835d68`

**Verified 2026-08-07 15:57 UTC:**
- `curl -sk $AMUX_URL/api/sessions/RTG-VS2017` returns 200 with the
  full session info dict (no more 404).
- Same fix applies to every session — verified against amux-helper.
- `~/.amux/sessions/RTG-VS2017.env` now has `CC_REMOTE="1"`; the
  auto-archive iterator will skip it going forward.
- Hot-reload preserved PID 1697930, systemd NRestarts unchanged at
  13.

**Result:** the dashboard card for RTG-VS2017 should no longer render
as "offline" — the detail endpoint it hits alongside `/peek` now
returns real data. Refresh the dashboard to see it.

**No regression in this morning's changes** (a307405 rehydrate,
a84ace6 AH-56, 2cf0807 AH-55) — those READ existing flags only; they
never write CC_ARCHIVED or archive a session. Behaviour is identical
for REMOTE sessions (Claude PID is live locally, so the PID guards
correctly skip false restarts).

**Trigger (Jeremy):** RTG-VS2017 (a REMOTE session — Claude Code
locally driving a Windows VS2017 build box) "appears offline but its
not". He suspected one of this morning's hibernated/archived flag
changes caused it.

**Actual root cause (proven by log, NOT a morning-change regression):**

`GET /api/sessions/<name>` (bare, no `/action` suffix) returns 404 for
this session. Same 404 in yesterday's log — this is a longstanding
gap.

```
2026-08-06 22:17:06 [...] GET /api/sessions/RTG-VS2017/peek       200
2026-08-06 22:17:07 [...] GET /api/sessions/RTG-VS2017            404
2026-08-07 15:51:17 [...] GET /api/sessions/RTG-VS2017/peek       200
2026-08-07 15:51:17 [...] GET /api/sessions/RTG-VS2017            404
```

The handler at ~L45308 parses `/api/sessions/<name>/<action>` and
runs branches only when `action` matches a known verb (`peek`,
`tasks`, `info`, `instructions`, etc). When `action` is empty (bare
GET), no branch fires and control falls through to
`return self._json({"error": "not found"}, 404)` at L45595.

Everything else about this session is fine:
- `env_file` exists, `tmux ls` shows `amux-RTG-VS2017` running.
- `/api/sessions` (list) reports `running: true, archived: false,
  status: 'idle'`.
- `/api/sessions/RTG-VS2017/peek` returns real Claude Code content.
- No `[auto-archive]` log line for RTG-VS2017. My morning commits
  (a307405 rehydrate, a84ace6 AH-56, 2cf0807 AH-55) don't write
  `CC_ARCHIVED`; they only READ existing flags. Nothing I shipped
  this morning could have archived a session.

**Ruled out (about my morning changes):**
- `a307405` (hibernation rehydrate) reads `meta.json` hibernated
  flag → sets an in-memory `actions["hibernated"]` bit. Never
  writes CC_ARCHIVED, never archives. Behaviour is identical for
  REMOTE sessions.
- `a84ace6` (AH-56 PID guard) BLOCKS an auto-restart when a live
  Claude PID exists. It never archives. On REMOTE sessions where
  Claude runs locally driving the remote box, PID is live → guard
  correctly SKIPS the restart. Safer, not more aggressive.
- `2cf0807` (AH-55 PID guard) same shape in `start_session` — SKIPS
  a respawn-pane -k when Claude is alive. Never archives.

None of these interact with REMOTE-ness. Jeremy's concern is
appreciated but the flags I added are read-only against existing
state; they don't set new state.

### Fix (two changes, one commit)

1. **Add a bare `GET /api/sessions/<name>` handler.** When `action`
   is empty, return `get_session_info(name)` — the same dict the
   list endpoint uses for each element. Fixes the 404 that made the
   dashboard render this and similar sessions as offline. This is
   what the dashboard was asking for all along and was just being
   silently refused.

2. **Add `CC_REMOTE` opt-in flag + honor it in `_auto_archive_idle`.**
   A REMOTE session's local tmux pane has no user activity (the real
   work happens elsewhere), so `pane_activity < cutoff` after 8h and
   auto-archive fires. Defensive belt-and-suspenders: any session
   with `CC_REMOTE=1` in its env is skipped by `_auto_archive_idle`.
   Then set `CC_REMOTE=1` on RTG-VS2017.env as a data fix so it
   never gets auto-archived again.

### Verification

1. Syntax check + hot-reload preserves PID.
2. `curl -sk $AMUX_URL/api/sessions/RTG-VS2017` returns JSON (200),
   NOT 404. Response matches the same session's entry in the list.
3. `grep 'CC_REMOTE=' ~/.amux/sessions/RTG-VS2017.env` shows the
   flag set.
4. Log line for auto-archive protection (when a REMOTE session
   would have qualified but was skipped) — not easy to prove
   directly; the code path is exercised by the skip clause.

### NOT doing

- No changes to the hibernation, auto-restart, or start_session PID
  guards. They're correct for REMOTE sessions today.
- No changes to `_watch_self`, /login, or threads work from this
  morning.
- Not fabricating a new REMOTE-detection heuristic based on the
  `REMOTE` prefix in `CC_DESC` — an explicit env flag is cleaner
  and doesn't misfire on descriptions.

---

## Plan for change: threads are Jeremy-only — hard rule + agent-facing docs (2026-08-07) — DONE ✅ commit `01c81fd`

**Verified end-to-end 2026-08-07 14:39 UTC (three tests, three log lines):**

1. **Cross-org POST** — RTG-ActAS → T-143 (SurfPrep):
   → 403 with `"You can't post to thread T-143 — it's not in your org.
   Thread T-143 belongs to org 'CD-SurfPrep'; your session
   'RTG-ActAS' is in org 'RTG'. Find the correct thread in your own
   org."` + hint pointing at board/channels.
   Log: `[threads] BLOCK cross-org reply: RTG-ActAS(org=RTG) → T-143(org=CD-SurfPrep)`

2. **Agent-to-agent same-org POST** — RTG-ActAS → T-155 with
   `to_session=RTG-Other`:
   → 403 with `"threads are for Jeremy only — agent-to-agent thread
   posts are strictly forbidden"` + hint pointing at board/channels.
   Log: `[threads] BLOCK agent-to-agent reply: RTG-ActAS → RTG-Other in T-155`

3. **Legit agent → Jeremy** — RTG-ActAS → T-155 with `to_session=""`:
   → 201 (accepted). Test message M-2935 was discarded after
   verification.

**Agent-facing docs updated in both places:**
- `~/.amux/memory/_global.md` — live file, every running agent's
  next composed MEMORY.md picks up the new rule.
- `GLOBAL_MEMORY_DEFAULT` in amux-server.py L9459 — seed for new
  installs.
- Section renamed "Threads — Jeremy's inbox, agent → Jeremy ONLY"
  with a HARD RULE callout, explicit list of alternatives (board
  for handoffs, channels for chatter), and the note that the server
  enforces the rule (returns 403).

**Together with `d25707b` (org isolation), threads are now:**
- Owned by one org (from first non-Jeremy participant).
- Cross-org reads → 404 (existence not leaked).
- Cross-org writes → 403 (with clear "not in your org" message).
- Same-org agent-to-agent writes → 403 (with clear "for Jeremy
  only" message).
- Agent → Jeremy (empty to_session) → allowed as before.
- Jeremy via dashboard → sees + posts everywhere as before.

**Jeremy 09:32 PT — hard rule:** "The Agents should talk using the
board not the threads. Threads are for ME, they are MY board. It's
strictly forbidden for agents to use the threads to communicate with
each other. They have an existing system, the boards, the threads
were designed for me so I could NOT have to see all the Agent
chatter. If that's not clear in what the agents get when they are
started up, then it needs to be."

**Current state (audit):**
- **Server enforcement (partial):**
  - `POST /api/threads`: already rejects `from_session AND to_session
    both non-empty` (agent creating a thread targeted at another
    agent) — L40378.
  - `POST /api/threads/T-N/messages`: does NOT reject when both are
    non-empty. An unrelated agent can reply into an existing thread
    and have `to_session` default to the OTHER agent (via
    `_other_party`), completing an agent-to-agent thread post. This
    is a gap.
  - The just-shipped org isolation (commit `d25707b`) blocks
    cross-org agent thread posts but ALLOWS same-org agent-to-agent.
    Jeremy's rule is stricter: NO agent-to-agent at all, same-org
    or not.
- **Agent-facing docs are wrong:** `~/.amux/memory/_global.md` line
  58 says: `### Threads — conversations with Jeremy OR between
  agents`. The whole section describes threads as an agent-to-agent
  channel. Same wording is in `GLOBAL_MEMORY_DEFAULT` in
  amux-server.py L9459 — the seed for new installs. Every agent that
  reads MEMORY.md at startup gets the wrong rule.

**Fix (one commit for code, one text edit for the live global):**

### Change 1 — Server guard on reply
In `POST /api/threads/T-N/messages`, right after `to_session` is
resolved (~L40476), add:
```python
if from_session and to_session:
    return self._json({
        "error": "threads are for Jeremy only — agent-to-agent thread posts are strictly forbidden",
        "hint": "Use POST /api/board (task handoffs, status) or "
                "POST /api/channels/<from>/<to>/messages (persistent 1:1 chatter). "
                "Threads are Jeremy's inbox; agents must not use them for peer traffic.",
    }, 403)
```
Dashboard exemption: N/A here — the reply handler already uses X-Amux-Session
for `from_session`; Jeremy through the dashboard has `from_session=""`, so
the guard's `if from_session and to_session` never fires for him.

### Change 2 — GLOBAL_MEMORY_DEFAULT rewrite
Replace the "Threads — conversations with Jeremy or between agents"
section (L9464 area in amux-server.py) with a rewritten section:
- Section header renamed: "Threads — Jeremy's inbox, agent → Jeremy ONLY".
- Explicit rule at the top: "Threads are Jeremy's personal inbox.
  Agent-to-agent thread posts are strictly forbidden and will be
  rejected 403 by the server. Use the BOARD for handoffs and status
  updates to other agents; use CHANNELS for two-way peer chatter."
- The routing/reuse/flag advice stays but explicitly framed as
  "Jeremy-facing".
- The "When to use Threads vs board vs channels" table gets
  rewritten to be crystal clear.

### Change 3 — Live `_global.md` rewrite
Same rewrite applied to `~/.amux/memory/_global.md` (the file every
running agent actually reads). Not a code change — just an edit to
the file. Every session that composes memory at next startup will
pick it up.

### Verification
1. Syntax check + touch + PID preserved.
2. Curl POST as agent → thread with `to_session` = another agent
   → 403 with new error.
3. `grep -n "strictly forbidden" ~/.amux/memory/_global.md` → matches.
4. Next start of any agent (or manual re-compose) → new text in their
   Claude memory.

### NOT doing
- No changes to the channels API (already the right place for peer chatter).
- No changes to the board API.
- No changes to /login, cache, or the org isolation shipped this morning.

---

## Plan for change: thread org isolation + T-143 cleanup (2026-08-07) — DONE ✅ commit `d25707b`

**Verified end-to-end 2026-08-07 14:33 UTC:**

Backfill migration:
- 116 existing threads got their org populated at startup (T-143 →
  `CD-SurfPrep`, correctly derived from the first message's
  from_session).
- 38 threads remain with empty org (Jeremy-only / legacy) — those
  stay open to everyone.

Enforcement live:
- `POST /api/threads/T-143/messages` with `X-Amux-Session: RTG-ActAS`
  → 403 with clear "thread scoped to org 'CD-SurfPrep'" message.
  Server log: `[threads] BLOCK cross-org reply: RTG-ActAS(org=RTG) → T-143(org=CD-SurfPrep)`.
- `GET /api/threads/T-143` with `X-Amux-Session: RTG-ActAS` → 404
  (existence not leaked).
- Dashboard (no X-Amux-Session) reads still see everything.
- `GET /api/threads` filtered per-agent: RTG-ActAS sees only the 25
  RTG threads + 36 empty-org threads.

T-143 cleanup:
- 11 RTG-ActAS messages moved out of T-143 into new thread T-155
  (`org=RTG`, title "RTG-ActAS status updates (moved from T-143 by
  cleanup)"). `parent_id` cleared on each moved message (cross-thread
  parent refs would fail the L40484 check).
- T-143 now: 48 Jeremy + 44 CD-SurfPrep + 4 Cypra-PAA + 2
  Cypra-EmailAgent = 98 messages. No RTG-* anywhere.
- The remaining Cypra messages are historical — they stay put. Going
  forward, Cypra sessions can no longer post to T-143 (different
  org, blocked by the new enforcement).

**Not shipping** (deferred until asked):
- Per-thread cross-org allowlist. If Jeremy needs Cypra-PAA to
  legitimately reply to a specific SurfPrep thread, we'll add a
  `thread_allowed_orgs` table then. For now: use board tasks or
  channels for cross-org handoffs.

**Trigger (Jeremy):** T-143 ("SurfPrep Repair System", primary agent
CD-SurfPrep) has 11 messages from RTG-ActAS about a completely
different project (Act software gate status). RTG has no business
posting into a SurfPrep thread. Confirmed via API pull:

```
44  CD-SurfPrep     (legit, thread owner's org)
11  RTG-ActAS       (CROSSING — CC_ORG=RTG, wrong project)
 4  Cypra-PAA       (legit cross-org handoff pattern — will be blocked by this fix)
 2  Cypra-EmailAgent (same — will be blocked)
48  Jeremy
```

Jeremy: "The Thread is created with a agents selected, that should be
its ORG and other ORGS can not read or post to those threads."

**Root cause:** the `threads` table has no `org` column (schema at
~L4861); the POST `/api/threads/T-N/messages` handler (~L40443) has
NO org check on the sender. Any authenticated agent can post to any
thread.

**Design choice (strict per Jeremy's ask):** thread carries an `org`
set at create time from the primary non-Jeremy participant. Any
sender whose `_session_org()` doesn't match is rejected. Dashboard
(Jeremy, identified by UI token) always exempt. Empty org = no
restriction (Jeremy-only threads, backward-compat).

**Known trade-off:** legit cross-org handoffs (Cypra-PAA fetching
Notion notes for CD-SurfPrep, Cypra-EmailAgent drafting for CD-SurfPrep)
will be blocked after this change. Those patterns will need to move to
channels or board tasks (Cypra was doing thread cross-posts because
we let it — the routing was never sanctioned). Jeremy's ask is
explicit; ship strict, adapt if he flags a specific handoff that
matters.

### Changes (one commit)

1. **Schema:** add `org TEXT NOT NULL DEFAULT ''` to `threads`.
   Migration runs at startup; safe idempotent `ALTER TABLE` guarded
   by a `PRAGMA table_info` check.
2. **Backfill on migration:** for every existing thread, derive org
   from the first non-Jeremy message's from_session OR to_session
   (whichever is set), via `_session_org(name)`. Threads with no
   non-Jeremy participant stay at `org=''`.
3. **POST `/api/threads`** (new thread): compute org from
   `from_session or to_session` and store it on the row.
4. **POST `/api/threads/T-N/messages`** (reply): if thread.org is
   non-empty, reject with 403 when sender's `_session_org` doesn't
   match. Dashboard (UI token) bypasses the check.
5. **GET `/api/threads`** and **GET `/api/threads/T-N`** (read):
   when request carries `X-Amux-Session` but NOT the UI token
   (i.e. an agent, not Jeremy), filter/reject threads whose org
   doesn't match the caller's org.
6. **Data cleanup for T-143:** one-shot Python inline script (run
   from this session, no code change needed) that (a) creates a new
   thread `RTG-ActAS status updates (moved from T-143)` with
   `org='RTG'`, (b) reassigns the 11 RTG-ActAS messages to it via
   direct SQL UPDATE, clearing their `parent_id` (cross-thread
   parent references are invalid per the L40484 check), (c) bumps
   `_threads_version` for the SSE clients.

### Verification

1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`.
2. Touch + hot-reload preserves PID.
3. Server log shows a `[threads-migration]` line on startup with the
   backfill count.
4. `curl -sk $AMUX_URL/api/threads/T-143 | python3 -m json.tool` —
   the returned thread has `"org": "CD-SurfPrep"` and NO messages
   from `RTG-ActAS`.
5. Curl POST to `/api/threads/T-143/messages` with
   `X-Amux-Session: RTG-ActAS` → 403 with a clear error naming the
   thread's org.
6. Same curl with `X-Amux-Session: CD-SurfPrep` → 200 (allowed).
7. Dashboard-attributed POST (UI token header) → 200 (Jeremy exempt).

### NOT doing

- No `thread_participants` allowlist table. Strict org rule only.
- No changes to the channels or board APIs.
- No changes to `send_text`, `_watch_self`, or the /login fix.

---

## Plan for change: fix linkifier (real location) + server-side OAuth prefix strip + revert shim (2026-08-07) — DONE ✅ BOOKED

**Confirmed working by Jeremy 09:10 PT** ("Hot DAMN!, you did it.
1. The link is clickable 2. the code is pasted in correctly").

**Lock-in commit `9c2aed0`** — added verbose warning banners at every
touchpoint (ansiToHtml.linkChunk, linkifyOutput, /send [oauth-strip],
doSend _pendingLogin, doSend [HH:MM] prefix builder) so a future edit
can't quietly regress the fix without seeing the warning.

**Leftover cleanup:** deleted `~/.amux/xdg-shim/` binaries left over
from the reverted MVP; codebase no longer manages them.

**Landed:**
- `6d19314` fix(peek): multi-line linkifier in ansiToHtml.linkChunk —
  the actual function used by the pane peek.
- `5624b97` fix(/login): server-side [HH:MM] strip when pane shows
  "Paste code here" prompt + shortened client `_pendingLogin` window
  from 15min → 2min.
- `684faf0` Revert xdg-open shim (`47da98f`).

**Verified 2026-08-07 14:02 UTC:**
- New linkifier regex is in the served HTML (curled the page and
  grep'd for the pattern).
- Prefix-strip regex passes 7 correctness cases (real OAuth codes,
  optional email, edge cases, negatives — see commit `5624b97`
  message for the tests).
- Shim endpoints are 404 after revert.
- Hot-reload preserved PID 1697930, systemd NRestarts unchanged at 13.

**Waiting on Jeremy** to hard-refresh Brave / clear cache and confirm:
1. Wrapped `/login` URL is one clickable link across all 3 lines.
2. Paste the OAuth code back — Anthropic accepts it (server strips
   the `[HH:MM]` prefix if it slipped through the client). Server
   log should show `[oauth-strip] session=X stripped_prefix_len=N`
   if the strip fired.

**Jeremy 08:57 PT — "The code sending still is not working. This is
Critical, Basic, we need to wrap this up. We need real solutions that
are stable and backed by qualified research not guessing."**

### Research (what I actually verified before writing code)

- `linkifyOutput` (~L23277) is called on ONE thing: message bodies in
  the messages panel (grep `linkifyOutput(` — one call site at L29156).
  It is NOT called on the terminal pane peek. My earlier "fix" in
  commit `51999a1` therefore did nothing for the pane.
- The pane peek is rendered by `ansiToHtml` (~L23187), which has its
  own nested `linkChunk` (~L23222) using the OLD single-line URL regex.
  That is why Jeremy still sees only the first line linkified.
- The `_pendingLogin` client-side flag from commit `5cc0c23` lives in
  `window` state. It breaks in three real scenarios:
  1. Cache/SW served OLD JS when `/login` was sent → flag never set →
     next paste gets prefixed.
  2. Tab was reloaded between `/login` and the code paste → flag lost.
  3. `/login` sent in tab A, code pasted in tab B → flag not shared.
- Server-side send (`POST /api/sessions/<name>/send`) does NOT peek
  the pane before delivering. So it has no idea what prompt the
  session is at.

### Fixes (three commits, one concern each)

1. **ansiToHtml.linkChunk multi-line URL fix** — apply the same regex
   change as `linkifyOutput` got in `51999a1`, but in the function
   that ACTUALLY renders the pane. Strip newlines from `href`, keep
   display text as-is.

2. **Server-side OAuth-prefix strip in `/send`** — before calling
   `send_text`, peek the last ~50 lines of the pane. If the pane
   ends in Claude Code's "Paste code here" prompt AND the incoming
   text begins with a `[HH:MM AM]` (optional email) prefix, strip
   that prefix and log the fact. Robust against ANY client cache /
   reload / cross-tab issue. Independent of the `_pendingLogin`
   client flag (which stays as a belt-and-suspenders that works when
   the JS is fresh).
   - Prompt signature (from Jeremy's screenshot 08:56 PT):
     `Paste code here if prompted >`.
   - Prefix regex: `^\[\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s+\S+@\S+)?\]\s*`.
   - Log line: `[oauth-strip] session=X stripped_prefix=<match>` — so
     Jeremy can see in server.log whether the strip fired.

3. **Revert `47da98f`** (xdg-open shim server-side MVP) — per Jeremy's
   ask "revert all the other ideas around opening the link". The shim
   is not the "opening the link" idea (auto-open was `3b3165b`, already
   reverted in `927ff9f`), but the shim was scaffolding for a similar
   idea and Jeremy wants scope pared back. Reverting removes: shim
   file writers, `_ensure_xdg_shim`, PATH prepend, `/api/browser-open`
   POST/GET, in-memory queue. `~/.amux/xdg-shim/` files stay on disk
   (harmless — no code prepends them to PATH after revert).

**NOT reverting** (unrelated to "opening the link"):
- `5cc0c23` (client-side prefix skip) — stays as best-effort. When it
  fires it saves a round-trip; when it doesn't fire, fix #2 catches it.
- `51999a1` (multi-line linkifier in `linkifyOutput`) — harmless on
  the message-body path, still correct there.
- `e62f040` (cache-control + SW version bump) — unrelated
  infrastructure.

**Side-effect Jeremy noticed at 08:47 PT** ("hit continue and it sent
that as the code"): the `_pendingLogin` flag consumes ANY non-slash
message within 15 min after `/login`. If he sends `/login`, then
types `continue` (say to steer another action), that message goes
through prefix-skipped and Claude Code treats it as the OAuth code.
Fix in the same commit as #2: shorten the client-side window from
15 min to 2 min, so the false-consumption blast radius is small.
The server-side pane-peek strip is the primary defense; the client
flag is just a nice-to-have.

**Verification (concrete, testable):**
1. Syntax check + hot-reload preserves PID.
2. `curl -sk https://localhost:8822/` | grep 'linkChunk' shows the
   new regex.
3. Simulate an OAuth-shaped POST /send to a session whose pane
   contains "Paste code here" — check server.log for `[oauth-strip]`.
4. Jeremy: hard-refresh Brave, `/login`, click the (now full) URL,
   sign in, paste the code back → success.

**What went wrong:** the earlier "linkifier fix" (commit `51999a1`)
patched `linkifyOutput` at ~L23277 — but the terminal pane peek does
NOT use `linkifyOutput`. It uses `ansiToHtml` (~L23187), which has
its OWN nested URL matcher `linkChunk` at ~L23222 with the same
single-line regex bug. `linkifyOutput` is only invoked on message
bodies (~L29156). That is why Jeremy's screenshot still shows only
the first line linkified — the fix went to the wrong function.

**This plan (Jeremy's terse ask — "Just make the link clickable. We
cant spend any more time on this. Revert all the other ideas around
opening the link"):**

### Step 1 — fix `ansiToHtml.linkChunk` at L23222–L23238
Apply the same regex change: allow newlines inside URLs when the next
line begins directly with URL-safe chars. Strip internal newlines from
`href` so the browser gets a valid URL; keep display text as-is so
pane layout is preserved.

### Step 2 — revert `47da98f` (xdg-open shim server-side MVP)
`git revert 47da98f --no-edit`. Removes the shim files (they will
still exist on disk but the codebase no longer manages them; can be
manually deleted), the `_ensure_xdg_shim` init, the PATH prepend in
start_session, and the `/api/browser-open` endpoints. Auto-open
`3b3165b` was already reverted in `927ff9f`.

**NOT reverting:**
- `5cc0c23` (skip `[HH:MM]` prefix on OAuth code paste) — this solves
  a real, separate problem (the code paste-back would still HTTP 400
  without it) and is not "about opening the link".
- `51999a1` (multi-line linkifier in `linkifyOutput`) — harmless
  and correct for the message-body path where it's actually called.
- `e62f040` (cache fix) — unrelated, infrastructure.

**Side-effect Jeremy noticed but did NOT explicitly ask me to fix:**
"I noticed that somehow I hit continue and it sent that as the code."
The `_pendingLogin` flag from `5cc0c23` swallows the NEXT non-slash
send within 15 minutes of `/login`. When Jeremy typed "continue" (or
anything else) after `/login`, that message went through without the
prefix and Claude Code treated it as the OAuth code. Not addressing
in this change — flagging in the DONE section for follow-up if he
asks.

**Verification:**
1. Syntax check.
2. Touch + hot-reload preserves PID.
3. Jeremy peeks at the `/login` pane in Brave (cache-safe since it's a
   fresh cache after switching browsers) — the whole URL should be one
   clickable link across all three wrapped lines.

---

## Plan for change: intercept Claude Code's `xdg-open` → forward to dashboard (2026-08-07) — SERVER-SIDE DONE ✅ commit `47da98f` (REVERTED — see plan above)

**Verified end-to-end server-side 2026-08-07 13:52 UTC:**
- Shim files exist at `~/.amux/xdg-shim/{xdg-open,open}` (chmod 755).
- Direct shim invocation with env vars POSTs to endpoint and exits 0.
- Shim without env vars exits 0 silently (safe fallback).
- `POST /api/browser-open` accepts valid payloads (200 `{ok:true}`),
  rejects invalid URL and missing session (400).
- `GET /api/browser-open?session=<name>` returns queued entries with
  timestamps. 5-min TTL and 5-entry cap enforced.
- Log line `[browser-open] session=X url=Y` appears in server.log.
- Hot-reload preserved PID 1697930, systemd NRestarts unchanged at 13.

**Existing amux sessions started BEFORE this commit will NOT have the
shim in PATH** (tmux `-e PATH=…` only applies at new-session time).
For those, either restart the session or invoke the shim by full path.
New sessions get it automatically.

**Deferred (still on the roadmap, not blocking):**
- Client-side banner UI (SSE-triggered or polling `/api/browser-open`)
  + click-to-open button. Blocked on Jeremy's Safari cache being
  verified working — no point shipping UI he can't see.
- Container session support — shim needs to be mounted into the
  container or written to the shared home. Follow-up.

**Verification recipe for a fresh session** (once Jeremy starts one):
```bash
# From inside a NEW amux session's tmux pane:
xdg-open https://example.com
echo $?     # → 0

# From the host, watch it land:
tail -f ~/.amux/logs/server.log | grep browser-open
curl -sk https://localhost:8822/api/browser-open?session=<name>
```

**Trimmed MVP scope** (client-side banner deferred while Jeremy's
Safari cache issue is unresolved — building it now would produce a
feature he literally can't see):
1. Shim script at `~/.amux/xdg-shim/xdg-open` + `~/.amux/xdg-shim/open`.
   Python script — POSTs `{session, url}` to
   `POST /api/browser-open`, exits 0.
2. `_ensure_xdg_shim()` helper — writes the shim (chmod 755) on server
   startup if missing.
3. `start_session` (host branch, single tmux new-session call at
   ~L11057) prepends `~/.amux/xdg-shim` to PATH via `-e "PATH=..."`.
   Container branch deferred — needs the shim mounted into the
   container's shared home.
4. `POST /api/browser-open` endpoint — validates URL, appends to a
   per-session in-memory queue (keep last 5, 5-min TTL), logs
   `[browser-open] session=X url=Y` to server.log.
5. `GET /api/browser-open?session=X` — returns the pending queue,
   used by client polling. Deferred client will hit this.

**Verify server-side works BEFORE building any UI:**
- Run `xdg-open https://example.com` inside an amux session's tmux.
- Check `~/.amux/logs/server.log` for a `[browser-open]` line.
- Check `curl -sk $AMUX_URL/api/browser-open?session=<name>` returns
  the URL in a JSON queue.
- The shim should exit 0 (echo `$?` in the pane → 0).

If all three green, the server side is proven. The client-side banner
(SSE-triggered + click-to-open button) becomes a small follow-up once
Jeremy's cache is sorted.

**Deferred within this MVP:**
- Container support (needs shim mounted or written into shared home).
- Client-side banner UI + SSE hookup.
- Fanout security (per-user filtering on cloud installs).
- Rate limiting on the endpoint (add if we ever see abuse; not
  needed for local dev).

**Risk audit (per Jeremy's caveat "we've made a whole lot of changes
trying to fix things and honestly, I don't know that any of those
changes actually did anything other than potentially introduce bugs
that we will find at a later date"):**
- PATH prepending affects every child process in the tmux session,
  not just Claude Code. If any child ALSO calls xdg-open (unlikely),
  it too gets intercepted. Harmless — worst case a stray banner.
- Shim exits 0 even if the POST fails. Claude Code will think the
  browser opened when it didn't. Trade-off accepted: better than the
  current "browser didn't open" fallback message, and the URL is
  still printed in the pane either way.
- New endpoint adds one route. No auth check on MVP — the endpoint
  only lives on `$AMUX_URL` which is already firewalled to the local
  network. On cloud, add auth when we build fanout.
- No changes to `_watch_self`, `send_text`, `_snapshot_all_sessions_
  inner`, or `start_session` PID guards. Isolated additions only.

**Ask (Jeremy 08:02 PT):** "Can we listen for claude codes attempt to
open a new browser, its trying to open the browser, is there any way
we can listen to that and use that or pass that along to the AMUX
browser etc?"

**Why this is interesting:** the "Browser didn't open? Use the url
below to sign in" message in the screenshot IS Claude Code's fallback
for when its subprocess call to `xdg-open`/`open` fails (headless
server has no display). If we intercept that call BEFORE it fails, we
can route the URL to the dashboard client and open the right tab.
Semantically cleaner than the pane-watching / polling approaches we
tried and reverted.

**Proposed architecture (a per-session PATH shim):**

1. **Server-side setup:** create a shim directory per session (e.g.
   `~/.amux/orgs/<org>/xdg-shim/`) containing two tiny scripts:
   ```
   xdg-shim/xdg-open  (executable)
   xdg-shim/open      (executable, same script — covers macOS-shaped calls too)
   ```
   Each script:
   - Reads `$1` (the URL).
   - POSTs `{session: $AMUX_SESSION, url: $1}` to
     `$AMUX_URL/api/sessions/<session>/browser-open` with the session's
     auth header.
   - Exits 0 (Claude Code sees success → does NOT print the "Browser
     didn't open?" fallback).

2. **Session env:** prepend `~/.amux/orgs/<org>/xdg-shim` to PATH when
   `start_session` composes the environment. The shim wins over the
   real `/usr/bin/xdg-open`. `$AMUX_URL` and `$AMUX_SESSION` are
   already exported per session (verified in current start_session
   code).

3. **Server endpoint** `POST /api/sessions/<name>/browser-open`:
   - Rate-limit (say 5 requests / 60s per session — avoid an
     accidental infinite loop from a misbehaving tool).
   - Log to server.log (`[browser-open] session=X url=Y`).
   - Emit an SSE event `{"type":"browser_open","session":X,"url":Y}`
     on the existing sessions SSE stream.

4. **Client:** the SSE handler for `browser_open` shows a
   **floating banner** at top-right: "<session> wants to open a URL —
   [Open in new tab]". The button is the user-gesture handler that
   calls `window.open(url, '_blank')`. Auto-dismiss after 60s.
   - Rationale: an auto `window.open()` from an SSE callback WILL be
     blocked by popup blockers (same trap we hit and reverted with the
     `_loginAutoOpen` code). A single-click button turns it into a
     legitimate user gesture — bulletproof.
   - The banner is preferable to a system Notification because
     Notification requires a permission grant and the banner works
     immediately across desktop + iOS PWA.

**Constraints / risks to think about BEFORE building:**
- **False positives:** any process that calls `xdg-open` in the
  session (a user typing it, a script) will pop a banner. Probably OK
  — feels like a useful side effect, not a bug. Rate-limiter covers
  loops.
- **Multi-client fanout:** if Jeremy has the dashboard open on desktop
  AND iPhone, both clients see the SSE event. Both banners fire; he
  clicks one, the other times out. Acceptable.
- **Container sessions:** shim path must be readable INSIDE the
  container. Two options: (a) mount the shim into the container at a
  known path, prepend that path to PATH in the container's env;
  (b) put the shim in the shared home already mounted per-org. Option
  (b) is less work — the shared home is already mounted at
  `~/.amux/orgs/<org>/home` per amux's current design.
- **Old sessions** started before the shim is installed won't see the
  new PATH. They'd need a restart to pick it up. Non-blocking — new
  sessions get it immediately, existing ones on next start.
- **Security:** endpoint takes an arbitrary URL and pushes it to
  clients. In a shared cloud install a session could theoretically
  spam other clients' banners. Mitigate: only fan out to clients
  authenticated as the session's owner (check `X-Amux-User-Email`
  match).

**NOT DOING as part of this idea:** any change to `send_text`, the
prefix-skip logic, the linkifier. Those stay as they are. This is
additive — a NEW code path, isolated to start_session env, one new
endpoint, one SSE event type, one client-side banner component.

**Scope estimate:** ~150 lines total (shim script + endpoint + SSE
event + banner + PATH plumbing in start_session). Half a session's
work with proper verification.

**When to build:** after Jeremy confirms the current linkifier /
prefix-skip / cache fixes are working end-to-end. This is quality-of-
life, not a bugfix — no rush.

---

## Plan for change: dashboard HTML cache — force Safari to see new JS on every ship (2026-08-07) — DONE ✅ commit `e62f040`

**Verified 2026-08-07 13:06 UTC:** `curl -I https://localhost:8822/`
now shows `Cache-Control: no-cache` on the HTML response. SW cache
version bumped to `amux-v0.8.10-2026-08-07`. Hot-reload preserved PID
1697930, NRestarts unchanged at 13.

**For Jeremy's IMMEDIATE next test** (existing SW install may still be
running the old version until Safari re-fetches sw.js on next nav):
- Safari → Develop → Empty Caches (Opt-Cmd-E) → Cmd-R.
- OR Develop → Service Workers → find amux → Unregister → Cmd-R.

After that one-time cleanup, future ships need only a plain reload
because `no-cache` forces revalidation.

**Trigger (Jeremy 08:02 PT):** shift-refresh in Safari didn't pick up
the `51999a1` linkifier fix. Pane still shows only the first line of
the URL linkified. The commit is on disk and the server is running
the new code (verified server-side), but Safari is serving stale HTML
from cache.

**Root cause:** two overlapping cache layers.
1. `_html()` (~L39391) sends the dashboard HTML with NO
   `Cache-Control` header. Safari applies heuristic caching (no
   `Last-Modified` → short but non-zero TTL, and Safari is notorious
   for being aggressive here).
2. The service worker (`SERVICE_WORKER` at ~L39006) uses network-first
   for `/`, which SHOULD be fine — BUT: the SW cache version has been
   fixed at `amux-v0.8.9` since the `cmux → amux` rename. Any cached
   fallback served by an older SW install could be stale.

**Fix (two parts, both cheap):**

1. **`_html` sets `Cache-Control: no-cache`** — clients may cache but
   MUST revalidate every navigation. With `no-cache` (as opposed to
   `no-store`) Safari can still send `If-None-Match` for 304 replies
   if we ever add ETags; today it just means "always ask the server."
   For an internal SPA that's already loaded via SW network-first,
   this changes almost nothing except making Safari behave.
2. **Bump SW cache version** from `amux-v0.8.9` to a fresh string
   (e.g. `amux-v0.8.10-2026-08-07`). The byte change forces every
   installed SW to update on next page load, and the `activate`
   handler deletes every cache whose name != new version — clearing
   any stale `/` HTML from prior SW installs.

**One-time manual workaround for Jeremy RIGHT NOW** (so he can verify
the linkifier fix without waiting for the next reload cycle):
- Safari → Develop menu → Empty Caches (Opt-Cmd-E), then Cmd-R.
- OR: Develop → Service Workers → find `amux` → Unregister → Cmd-R.

**Verification:**
1. Syntax check + `os.execv` hot-reload preserves PID.
2. Curl `-I https://localhost:8822/` shows `Cache-Control: no-cache`.
3. Jeremy hard-refreshes (or does the manual workaround above) —
   linkified URL now spans all three wrapped lines.

**Related but deferred (Jeremy's second Q — 08:02 PT):**
"Can we listen for claude codes attempt to open a new browser… pass
that along to the AMUX browser?" — Claude Code shells out to
`xdg-open`/`open` when it prints the login URL (the screenshot's
"Browser didn't open? Use the url below to sign in" is the fallback
that fires when the subprocess fails). We could shim `xdg-open` per
session so it POSTs to amux instead → SSE-push → client opens tab.
Bigger scope — deferring to a separate research + plan section after
the cache fix lands and the linkifier is confirmed working.

---

## Plan for change: linkifier handles multi-line wrapped URLs + revert auto-open (2026-08-07) — DONE ✅

**Landed:**
- `51999a1` fix(linkify): reconstruct URLs that tmux wrapped across multiple lines
- `927ff9f` Revert "feat(dashboard): /login auto-opens the auth URL in a new browser tab"

**Verified 2026-08-07 12:58 UTC:** post-commit `touch amux-server.py`
triggered `os.execv`, PID 1697930 preserved, systemd NRestarts
unchanged at 13, dashboard HTTP 200. `doSend` still has the
prefix-skip logic from `5cc0c23`; the auto-open helpers and the
`_loginAutoOpenStart(name)` call inside `doSend` are gone.

**Live UX verification (needs Jeremy):** hard-refresh dashboard,
peek at any session showing a wrapped URL (or trigger `/login`), the
whole URL should be one clickable link that opens correctly.

**What Jeremy saw (screenshot 07:53 PT):** the terminal peek IS
linkifying the `/login` OAuth URL, but only the FIRST wrapped line.
Claude Code prints the full URL across three physical terminal lines:
```
https://claude.com/cai/oauth/authorize?code=true&client_id=…&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foa
uth%2Fcode%2Fcallback&scope=…
LxMSsJVo9QpTIykzhwdnq0ftVHfXI1OOWJMjoNl2M&code_challenge_method=S256&state=…
```

`linkifyOutput` (~L23288) uses `https?:\/\/[^\s<>\]\)'"``,;]+` — `\s`
includes newline, so match stops at the first wrap. Result: only the
first line of the URL is clickable and it's an incomplete URL that
would 404 (or worse, redirect somewhere unrelated).

**Jeremy's suggested fix (this is exactly right):** teach the
linkifier to reconstruct wrapped URLs. Then the click-through works
naturally and the pre-opened-blank-tab auto-open (commit `3b3165b`)
becomes unnecessary — revert it.

**Plan (two steps, in order):**

### Step 1 — fix linkifier

In `linkifyOutput` at ~L23288, extend the URL regex to allow newline
IF the next line begins directly with URL-safe chars (no leading
whitespace — which would be a genuine wrap continuation from tmux, not
a new line of output). Then when building the HTML `<a>`, strip
newlines from the `href` so the browser gets a valid single-line URL,
but leave the display text as-is (spans multiple visual lines,
preserving pane layout).

Concretely:
```js
const urlRe = /https?:\/\/(?:[^\s<>\]\)'"`,;]|\n(?=[A-Za-z0-9%\/&?=_\-.+~]))+/g;
// ...when emitting:
const cleanHref = match.value.replace(/\n/g, '');
html += `<a href="${esc(cleanHref)}" target="_blank" rel="noopener noreferrer">${esc(match.value)}</a>`;
```

Failure modes considered:
- False positive across two different URLs on consecutive lines: only
  if the second URL starts with `[A-Za-z0-9%\/&?=_\-.+~]` AND there's
  NO indentation before it. Terminal output almost never renders two
  bare URLs back-to-back with no indent or blank line. Acceptable.
- False positive across URL then a regular word on next line: word
  would need to start at column 0 with alphanumeric — possible but
  extremely rare mid-URL, and worst case is a slightly-too-long link
  target (still parses as a URL, just with garbage query string).
- Trailing punctuation stripping (`.,;:!?)` at end of match value)
  still runs — needed because the last line often ends the URL with
  `)` or `.` in normal prose.

### Step 2 — revert auto-open commit `3b3165b`

`git revert 3b3165b --no-edit`. The auto-open feature was
belt-and-suspenders; with the linkifier fix, the natural user flow is:
- `/login` → send bar (still triggers the prefix-skip flag from
  `5cc0c23` for the code paste-back)
- User clicks the linkified URL in the pane → new tab, no popup-blocker
  concerns (it's a real user click on a real link)
- User signs in, copies code, pastes into send bar → code goes raw

Both steps are independent — Step 1 stands on its own; Step 2 is pure
cleanup of the now-superseded feature.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
   after each step.
2. Touch + PID-preserved hot-reload after each commit.
3. Live: hard-refresh dashboard; peek at any session's pane showing
   the OAuth URL; the whole URL is one clickable link that opens the
   correct target.

---

## Plan for change: `/login` auto-open browser tab to the OAuth URL (2026-08-07) — DONE, then REVERTED (see next section)

Original commit `3b3165b` — auto-open blank tab + poll for URL.
Superseded by the linkifier fix above. Reverted for simplicity per
Jeremy's suggestion after seeing that the linkifier gets us the same
UX with fewer moving parts.

**Verified server-side 2026-08-07 12:20 UTC:** post-commit `touch
amux-server.py` triggered `os.execv`. PID 1697930 preserved, systemd
NRestarts unchanged at 13, dashboard HTTP 200. New JS live on next
page reload.

**Live UX verification (needs Jeremy in the browser):**
1. Hard-refresh dashboard (Cmd/Ctrl-Shift-R).
2. Pick a session, type `/login`, hit Send.
3. Expected: a new browser tab opens immediately (about:blank), then
   within a few seconds navigates to `https://claude.com/cai/oauth/…`.
4. Complete the OAuth flow, copy the code, paste into send bar.
5. Expected: code goes through raw (from commit `5cc0c23`), Claude
   accepts, no HTTP 400.

**Fallback path (popups blocked):** if the browser blocks
`window.open()`, the URL is copied to clipboard and a toast says
"Login URL copied — paste into a new tab to sign in". User can paste
into a new tab manually.

**If the auto-open doesn't fire:** check DevTools console. Common
causes:
- Popup blocker returned null → clipboard fallback should have fired
  instead.
- URL regex doesn't match Claude Code's actual output — capture the
  pane and update `_LOGIN_OAUTH_URL_RE` in doSend area (~L21247).
- Peek endpoint returning no matches — inspect `d.output` in
  DevTools.

**Ask (Jeremy 07:14 PT):** "When I use the login command, would it be
possible to detect when it gives me the URL to use to log into and
AMUX open a new tab automatically to that URL."

**Chosen scope (Jeremy):**
- Claude Code `/login` only. Ignore Codex/Gemini/Gmail for now.
- Open at most once per `/login` — if Claude reprints the URL later
  in the same flow, don't reopen. To re-trigger, resend `/login`.

**URL Claude Code prints (Jeremy 07:15 PT sample):**
`https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-…&response_type=code&redirect_uri=…`

Detection regex: `https:\/\/claude\.com\/cai\/oauth\/[^\s"'<>]+`

**Popup-blocker trap** (why prior "just window.open() when we see it"
attempts would fail even if the code is right): browsers require
`window.open()` to run INSIDE the user-gesture callback. If we detect
the URL 1–3s later via polling and call `window.open()` from that
timer callback, the browser silently kills it.

**Approach — the pre-opened-blank-tab trick:**
1. INSIDE the `doSend` click handler (same tick as the user's click),
   when `/login` is being sent: `window._pendingLoginTab = window.open('about:blank', '_blank')`.
   That tab is now "authorized" by the click. If it returns null, the
   user has popups blocked; fall back to a toast with a clickable link.
2. Kick off a polling loop that fetches `/api/sessions/<name>/peek`
   every 500ms for up to 30s.
3. On each response, extract URLs matching the regex above; take the
   LAST match (most recent scrollback position). If found:
   - `window._pendingLoginTab.location.href = url`
   - Stop polling, clear the flag.
4. If 30s elapse with no match: close `_pendingLoginTab` if it's still
   `about:blank` (don't disturb the user if they've navigated it).
5. If a new `/login` fires while polling is in flight: cancel the
   prior poll and open a fresh tab.

**Deliberate constraints:**
- Client-side only. No server changes. Reuses existing `/peek` API.
- Localized to `doSend` — same function we just modified for the
  `[HH:MM AM]` prefix fix. Keep both fixes cohesive.
- No new global state beyond `_pendingLoginTab` and a poll-cancel
  handle. Both are cleared on completion / failure.
- Do NOT touch `send_text`, `_snapshot_all_sessions_inner`, or SSE.
  That's out of scope and prior investigations warned to avoid
  drive-by changes there.

**Expected behavior:**
- Type `/login` in the send bar, hit Send.
- A new browser tab opens immediately at about:blank.
- Within a few seconds, that tab navigates to the real Claude auth URL.
- Log in, get the code, paste into the send bar. (The prior fix
  ensures the code isn't prefix-mangled.)
- If popups are blocked: toast appears with a clickable link.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`.
2. Touch → hot-reload preserves PID (SESSION-RESTART CHAIN rules).
3. Live browser test: hard-refresh dashboard, /login on a real session,
   confirm the new tab opens and navigates.

**Rollback:** revert one commit. Change is self-contained in doSend.

---

## Plan for change: `/login` OAuth code paste → HTTP 400 (2026-08-07) — DONE ✅ commit `5cc0c23` (awaiting live Jeremy verification)

**Verified server-side 2026-08-07 12:02 UTC:** post-commit `touch
amux-server.py` triggered the `os.execv` path. PID 1697930 preserved,
systemd NRestarts unchanged at 13, dashboard HTTP 200. New client code
loaded into every fresh page reload.

**Live UX verification (needs Jeremy in the browser):**
1. Hard-refresh the dashboard (Cmd/Ctrl-Shift-R) to pick up the new
   JS.
2. Open any session, run `/login` in the send bar.
3. Do the browser OAuth dance, copy the code.
4. Paste the code into the send bar and hit Send.
5. Expected: pane receives the code EXACTLY (no `[HH:MM AM]` prefix),
   Claude Code accepts it, no HTTP 400.
6. Send a normal message afterwards — expected: timestamp prefix
   returns (flag was cleared).

**If it still fails:** capture the actual pane contents at the OAuth
prompt (`amux peek <session>`) and add to this section. The most
likely follow-up would be that Claude Code's OAuth prompt has some
OTHER text-mangling issue (bracketed paste, autocomplete). If it fails
identically to before, the client-side fix didn't apply — check
DevTools console for the `_pendingLogin` object shape and confirm the
JS reloaded.

**Symptom (Jeremy):** `/login` opens a browser URL, he authorizes,
copies the code back, pastes into the dashboard send bar, hits Send.
Anthropic returns HTTP 400 (invalid code). Multiple prior attempts to
fix have not worked. He suspects the prior changes may have introduced
latent bugs without observable symptoms yet.

**Root cause (identified 2026-08-07 by direct code inspection):** the
client-side `doSend` (~L21162) prepends a human-readable timestamp
prefix to every message that does not start with `/[a-z]`:

```js
const isSlashCmd = /^\/[a-z]/.test(text.trim());
let payload = text;
if (!isSlashCmd) {
  payload = `[${ts}${author}] ${text}`;
}
```

- `/login` itself is a slash command → sent verbatim → OAuth flow starts
  correctly.
- The OAuth code Jeremy pastes back is NOT a slash command → gets
  prepended with `[HH:MM AM] ` (and `_cloudEmail` if set).
- `send_text` on the server sees a `≤400 char` message and uses
  `send-keys -l`, delivering `[HH:MM AM] <REAL_CODE>` verbatim to
  Claude Code's OAuth-code readline prompt.
- Claude Code POSTs `[HH:MM AM] <REAL_CODE>` to Anthropic → 400.

**Ruled out (confirmed by inspection):**
- `send_text` (~L11536) does NOT mangle short text through `send-keys -l`
  by itself for URL-safe chars — the character stream is preserved
  verbatim (verified previously in RESUME-HERE's "Bug A" investigation;
  the paste-buffer rewrite at L11615 covers the `>400` branch only).
- No `Escape`, `C-u`, or picker-close key is currently sent before the
  literal typing in the small-message path (that logic was removed in
  earlier fixes — see `a9b0352`, `60f1059`).
- No other `/send` caller in the JS bundle adds the timestamp — only
  `doSend`. The bug is localized to the send-bar path Jeremy uses.

**Why prior attempts failed to land the fix:** the "Bug A" work in
prior sessions focused on tmux-side character corruption (paste-buffer
vs send-keys) rather than the client-side prefix. The prefix is easy
to miss because the JS is 20K lines away from `send_text` in the same
file, and normal messages LOOK fine in the pane (timestamps are
expected human context, not corruption).

**Two candidate fixes, tradeoffs:**

1. **Session-scoped "expecting OAuth code" flag** (matches Jeremy's
   mental model — "listen for /login, then skip the prefix on the next
   real message"):
   - On `doSend` with slash command that starts with `/login`, set
     `window._pendingLogin[name] = Date.now()`.
   - On next `doSend` with non-slash text AND flag was set within last
     ~15 min, skip the timestamp prefix and clear the flag.
   - Pros: matches Jeremy's exact wording, minimal server changes.
   - Cons: false-triggers if the user types `/login` then decides to
     send a normal message; false-misses if the flag times out. Also
     doesn't help other unusual prompts that expect raw input.

2. **Server-side pane-state detection** (robust, no client memory):
   - The server, on POST `/api/sessions/<name>/send`, peeks the pane
     tail. If it matches an OAuth-code-prompt pattern
     (e.g. `Paste code`, `Enter code`, `authorization code`), STRIP any
     `^\[\d{1,2}:\d{2}\s?(AM|PM)\]\s*` prefix before calling
     `send_text`. (Server can't "know" client added it, but it can
     recognize the pattern and remove it — timestamps of this exact
     shape are never legitimate OAuth code prefixes.)
   - Pros: no client state, no flag races, self-heals for other raw-
     input prompts if we generalize the pane-state check.
   - Cons: fragile regex — Claude Code's OAuth prompt text may change
     between releases. Would need a match test on the actual current
     Claude Code /login screen (which we haven't captured yet).

3. **Combined** (belt-and-suspenders): use (1) as the primary trigger
   (fast, no pane read) and (2) as a safety net.

**Recommendation:** Option 1 first — it directly answers Jeremy's
described flow ("when I use /login and then when I give you the token
which could be not immediately after that"). Small, targeted, easy to
revert. If it proves flaky in practice, add (2).

**Verification plan (regardless of option chosen):**
1. Syntax check + `os.execv` hot-reload preserves PID (per SESSION-
   RESTART CHAIN rules).
2. Peek a live pane after `/login` to CAPTURE the actual OAuth prompt
   text; save the capture into this doc for future reference.
3. Reload the dashboard, click into a test session, run `/login`,
   navigate the login flow in a browser, paste the code into the send
   bar, hit Send. Expect: NO timestamp prefix in the pane; Claude Code
   accepts the code; no HTTP 400.
4. Send a normal message afterwards. Expect: timestamp prefix returns
   (flag was cleared).

**Not doing (audit note per Jeremy's caveat):** any refactor of
`send_text` character-encoding logic, any change to the `>400` paste-
buffer path, any change to `apiCall`. Those are prior in-flight
concerns from RESUME-HERE's "Bug A" that are NOT relevant to this
specific 400 bug.

---

## Plan for change: friendly error toast when archiving a pinned session (2026-08-07) — DONE ✅ commit `391da8a`

**Verified 2026-08-07 11:37 UTC:** post-commit `os.execv` hot-reload
kept PID 1697930, systemd NRestarts unchanged at 13. Server-side error
text unchanged. UX toast verification needs a browser click — Jeremy
to confirm on a pinned session.

**What:** In `archiveSession` (JS, ~L21010), stop routing through
`apiCall` (which swallows the response body and shows a bare
`"Error: 403"` toast). Fetch directly, and on non-2xx read the JSON
error and surface it as a readable toast.

**Why:** Jeremy 2026-08-07: "the dashboard should let me know via a
message that I cannot archive pinned sessions. Instead of showing me an
error message." Trigger: he clicked Archive on ShareScore-Main (pinned),
saw only `Error: 403`, had to ask what was wrong.

The server already returns
`{"error": "cannot archive pinned session — unpin first"}` with status
403 (`amux-server.py:45650`). The bug is client-side — `apiCall`
(~L19377) intercepts the non-2xx, calls `showToast('Error: ' + r.status)`
and returns null. The body never reaches `archiveSession`.

Narrow fix (this change only): bypass `apiCall` in `archiveSession`,
do the fetch inline, and show the parsed `error` field on failure.
Do NOT change `apiCall`'s default behavior — other callers rely on it,
and generalizing here would sprawl the change.

**Expected behavior:**
- Success: existing behavior — `"<name> archived"` toast + refresh.
- Failure with parsed error: toast `"<error message>"` (e.g. "cannot
  archive pinned session — unpin first").
- Failure without parsed error (network / non-JSON): toast
  `"Archive failed (HTTP <status>)"`.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`.
2. `touch amux-server.py` → confirm hot-reload via `os.execv`, PID
   preserved.
3. In the dashboard, pin a test session (or use an already-pinned one),
   click Archive → expect the "cannot archive pinned session — unpin
   first" toast, no bare `Error: 403`.
4. Unpin, click Archive → expect success toast + card disappears.

**Rollback:** trivial — revert this one function.

---

## Plan for change: verbose linking docs on session-restart machinery (2026-08-07) — DONE ✅ commit `b2c0fa1`

**Verified 2026-08-07 11:32 UTC:** post-commit `touch amux-server.py`
triggered the `os.execv` path. PID 1697930 preserved, systemd NRestarts
unchanged at 13, log confirmed `[restart] pid=1697930 direct execv →`
followed by `[startup] pid=1697930`. Pure comment/docstring additions
(147/+143 −4), zero logic change.


**What:** Add verbose docstring/comment blocks to the amux-server.py
functions that participate in the session-restart chain, explaining how
they link together. Areas to document:

1. `_watch_self` (~L46836) — mtime watcher. Explain: what triggers it,
   why direct `os.execv` (not `server.shutdown()`) is required, the
   systemd `KillMode=control-group` interaction, and the guarantees
   `os.execv` provides (PID preservation → systemd sees no exit → no
   cgroup slaughter → agent sessions live).
2. `_snapshot_all_sessions_inner` (~L3959) — hibernation rehydrate + AH-56
   PID cross-check. Explain: why the in-memory `hibernated` flag is
   volatile across restart, what pushover storm it prevents (ShareScore),
   and why `_at_shell_prompt` alone is insufficient (text heuristic false
   positives right after execv → need `_find_claude_pid` cross-check).
3. `start_session` (~L10623) — AH-55 belt-and-suspenders PID guard.
   Explain: how `is_running() → _at_shell_prompt` can transiently false-
   negative right after execv, why that would take the tmux-exists
   `respawn-pane -k` path and kill a healthy claude, why direct PID check
   is authoritative.
4. Cross-references — each doc block should point at the others so a
   reader of any one function sees the whole chain.

**Why:** Jeremy 2026-08-07 06:24: "add verbose documentation to the
scripts that you changed around that area that you changed and how they
are linked to each other and how they connect that way a future you can
read those comments and understand how all these puzzle pieces go
together on the server."

**Expected behavior:** No runtime change. Zero logic edits — only
docstrings and comment blocks. The Python syntax check must pass. mtime
change triggers watcher → NEW execv path → PID preserved (already
verified working post-`277855c`).

**Verification steps:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` —
   syntax OK.
2. Confirm working-tree `git diff` shows only added comment/docstring
   lines, no code edits.
3. `touch amux-server.py` → server restarts via `os.execv`, PID stays
   the same. `pgrep -f amux-server.py` before and after should match;
   `systemctl --user show amux.service --property=NRestarts` should not
   change.
4. `git add amux-server.py && git commit` with `docs(server):` prefix.

**Rollback:** `git revert <hash>` if anything breaks — docstring-only,
so revert is safe.

---
