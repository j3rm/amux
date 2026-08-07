# RESUME HERE — permanent amux-server.py worklog

**If you are Claude and you are about to edit `/mnt/gitdata/amux/amux-server.py`, this file is mandatory.** Every change must be planned here BEFORE you edit code. Completed plans stay in place as history — do NOT delete them. Read this file at the start of every session before touching amux-server.py.

Last updated: 2026-08-07 13:30 UTC / 06:30 PT

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

## Plan for change: verbose linking docs on session-restart machinery (2026-08-07) — IN PROGRESS

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
