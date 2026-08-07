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
