# RESUME HERE — permanent amux-server.py worklog

**If you are Claude and you are about to edit `/mnt/gitdata/amux/amux-server.py`, this file is mandatory.** Every change must be planned here BEFORE you edit code. Completed plans stay in place as history — do NOT delete them. Read this file at the start of every session before touching amux-server.py.

Last updated: 2026-10-12

## Plan for change: Account-level usage meter (3 stacked bars, Jeremy 2026-10-12) — IN PROGRESS

**Trigger:** Jeremy ruled 12:56 PM: he wants three stacked progress bars at the top
of the dashboard showing % of weekly cap used for each of his 3 accounts
(1 Codex, 2 Claude: NWDDI and J3 STWR), plus days to reset. The crude
provider-only chips (prior plan, DONE) stay as the fallback the bars
degrade to on no-data.

**Design (ruled by Jeremy 2026-10-12 15:50):**
- One accountant session per account, agent-side parse, POSTs to amux API.
- Mapping (ruled):
  - `codex` -> `CD-Audit-Codex` (only live codex session with working auth)
  - `claude-nwddi` -> `CD-WattcoAccMigration` (CD-* fleet)
  - `claude-j3stwr` -> `Ember-Research` (Ember/RTG fleet)
- Idle poll only. Scheduler checks session idleness before sending the prompt.
- On no reading or stale (> 7h) data, chip shows `?` so Jeremy can tell parse
  vs transport failure from working-nothing-to-report.

**Scope (amux-server.py only):**

1. **SQLite migration** (new table + register in schema):
   ```sql
   CREATE TABLE account_usage (
     account         TEXT PRIMARY KEY,
     percent         REAL,
     reset_at        INTEGER,
     source_session  TEXT,
     reported_at     INTEGER NOT NULL,
     raw_text        TEXT
   )
   ```

2. **Endpoints:**
   - `POST /api/usage` body `{account, percent, reset_at, raw}`.
     `X-Amux-Session` required; must match `_ACCOUNT_REPORTERS[account]`
     (reject 403 otherwise). UPSERT by account.
   - `GET /api/usage` returns the three rows plus a derived
     `days_to_reset` and `stale` flag.

3. **Constant** `_ACCOUNT_REPORTERS` dict (session -> account) with the
   3 mappings above. Used by the endpoint auth gate and the scheduler.

4. **Scheduler integration** (reuse existing `schedules` table + `_run_schedule`):
   - Create 3 cron entries (`0 */6 * * *`) after server first boots with this
     migration applied. Each sends a specific prompt to its session
     telling the agent: run your TUI /status, parse the weekly %
     and reset time, POST to `/api/usage` with the account key.
   - Idleness gate: before `send_text`, check tmux pane bottom lines for
     a known "working" marker; if seen, log skip and leave for next window.

5. **UI (replace header chips body):**
   - Keep the `#weekly-meter` container, swap children for 3 `.wm-bar`
     rows (account label, filled bar, "X% / Nd" suffix).
   - On GET /api/usage, render bars. On stale rows, bar fades + suffix
     reads `?`.

6. **Call site**: add a GET /api/usage fetch to the same tick as
   `updateRateLimitPill` + `updateWeeklyMeter`. Keep the per-provider
   chip fallback behind `[data-mode="chips"]` for the no-data case.

**Verify:**
- `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
- POST a synthetic reading as each reporter (curl with X-Amux-Session header)
  and confirm GET returns it with correct days_to_reset math.
- Confirm 403 on POST from a non-reporter session.
- Confirm the 3 schedule rows exist after boot.

## Plan for change: Header weekly-cap chips (crude usage meter, Jeremy 2026-10-12) — DONE

**Trigger:** Jeremy wants a "Weekly Usage" meter in the dashboard header
(empty slot right of the notification bell, visible in the screenshot
at /home/jwesley/.amux/uploads/813e0da1-Screenshot_2026-10-12_at_12.44.45_PM.png).
Full account-level usage percent needs separate per-account polling of
Anthropic + OpenAI (option 1); for now (option 2 of the choices I
offered), reuse the data the rate-limit watchdog already captures to
show whether EACH provider's weekly cap has been hit, and if so, when
it resets. Zero new polling.

**Scope (amux-server.py only — HTML+CSS+JS inside the single file):**

1. **HTML** (new element, inside the header right-group, FIRST child
   before `#org-switcher-wrap`):
   ```
   <div id="weekly-meter" class="weekly-meter">
     <span class="wm-chip wm-claude" title=""><span class="wm-dot"></span>Claude <span class="wm-time" id="wm-claude-time">ok</span></span>
     <span class="wm-chip wm-codex" title=""><span class="wm-dot"></span>Codex <span class="wm-time" id="wm-codex-time">ok</span></span>
   </div>
   ```
   Two chips, one per provider. Default dim-green dot + "ok". When a
   session with that provider has `rate_limit_weekly` and
   `rate_limited_until > now`, chip flips to red + shows duration to
   reset (e.g. "2d 4h"). Click target: already covered by the existing
   `#rate-limit-pill` next to it — chips are informational, no new JS
   click handlers.

2. **CSS** (new block near the existing `.btn-rate-limit` rules):
   `.weekly-meter`, `.weekly-meter .wm-chip`, `.wm-dot`, `.limited`
   variants, and a `@media (max-width: 600px)` rule hiding the
   duration text (keeping just the dot + provider name) on mobile.

3. **JS** (new helpers, after `_scrollToFirstRateLimited`):
   - `_wmFmtDur(secs)`: short duration formatter ("45m", "4h", "2d 3h").
   - `updateWeeklyMeter()`: walks `sessions`, groups by provider
     (claude / codex), picks the EARLIEST `rate_limited_until` for
     each where `rate_limit_weekly` is true. Updates chip color +
     title. If no weekly cap hit, chip reads "ok" (dim green).

4. **Call site:** inside the existing `updateRateLimitPill` call-site
   (the function that already runs every time sessions refresh —
   line ~22351), add `updateWeeklyMeter();` right after it. One
   extra pass over `sessions`, no new fetches.

5. **No server changes.** All data (session.provider,
   session.rate_limited_until, session.rate_limit_weekly) is already
   in the `/api/sessions` payload.

**Explicit non-goals:**
- Does NOT show "X% weekly used" — that needs account-level usage
  polling (option 1), deferred until Jeremy picks it up.
- Does NOT fire pushes / notifications — purely visual.
- Does NOT change the existing rate-limit pill behavior — chips sit
  alongside it, redundant for the "weekly" case but useful because
  the pill vanishes when count hits 0; chips show a steady "ok" so
  Jeremy can see at a glance there's a live indicator (empty header
  = either healthy OR broken).

**Verify:**
- Python syntax ok.
- Open dashboard: chips visible in the slot the screenshot marked.
- Simulate hit: temporarily set `rate_limit_weekly` on a session via
  the server's internal state (or wait for an organic hit).
- Mobile (375px width): chips truncate to dot + provider label, no
  overflow.

---

## Plan for change: Stale-todo reboost — rate-limit skip, count-aware escalation, Jeremy loop (Jeremy 2026-10-12) — DONE

**Trigger:** Jeremy noticed two token-burn patterns in production:
1. The stale-todo reboost re-pushes items to agents that are
   rate-limited or credit-limited. They can't act, but the pane still
   wakes and the LLM reads the push.
2. When an agent CAN read but can't do the task, it tends to answer
   "yeah I know, can't do that" instead of changing the item's status.
   Reboost keeps pinging; tokens keep burning.

Jeremy's rule: ignoring a board nudge is not an option. The nudge
itself must spell out the escape hatch (change status, state why),
and after N nudges without a status change, we stop pinging the
agent and surface the item to Jeremy via a thread so he can
intervene.

**Scope (amux-server.py only):**

1. **Schema.** Add column `stale_escalated INTEGER NOT NULL DEFAULT 0`
   on `issues`. Set to 1 when the item has been escalated to Jeremy by
   the sweep — guarantees at-most-once escalation and suppresses
   further reboosts.

2. **`_sweep_stale_todos_reboost` — skip condition.** Before boosting
   a row, read the assignee's session state (rate_limited_until,
   credit_limited). If either is active, SKIP the reboost (do not
   touch pos, do not re-notify, do not increment boost count), and
   slog `[stale-todo-reboost] skip <id>: assignee rate_limited|credit_limited`.
   Rationale: rate-limited pushes are wasted — they wake the pane but
   can't be acted on, and they count as token noise for Jeremy's
   budget.

3. **Count-aware nudge text.** The current reboost always calls
   `_notify_session_of_task(sess, iid, title)` which emits the same
   generic "new task" line. Replace that call (inside the reboost
   loop ONLY — unchanged on first-mint) with a new helper
   `_notify_session_of_stale_todo(sess, iid, title, boost_count,
   flag_threshold)` that emits text keyed on count:

   - **boost 1 (first reboost at ~30min stale):**
     `"Board nudge (1st reboost): <id> has sat in your todo for ~30m.
     If you can't start it, change its status (backlog with a
     one-line reason, or discarded with VOID: <reason>). Ignoring the
     ping = continued reboosts = token burn. Status change stops the
     loop."`

   - **boost 2 (~1h):**
     `"Board nudge (2nd reboost): <id> still 'todo' after ~1h. You
     MUST respond — either claim (status=doing) or park (status=
     backlog + reason). If you cannot do the work, the correct
     answer is a status change, not silence. 2 more reboosts and
     this escalates to Jeremy."`

   - **boost 3 (~1.5h):**
     `"Board nudge (3rd reboost, FINAL warning): <id> still 'todo'.
     Next reboost escalates to Jeremy and parks this item to
     backlog. Change status now (doing / backlog / discarded) with
     a one-line reason."`

   - **boost N (= `_flag_threshold`, default 4, ~2h): escalation path
     — see item 4.**

4. **Escalation at `_flag_threshold`.** On the 4th consecutive boost
   (configurable via `AMUX_STALE_TODO_BOOST_FLAG_COUNT`), DO NOT
   boost or ping the assignee. Instead:
   - Set `stale_escalated = 1` on the row (sweep skips it forever).
   - Set `status = 'backlog'` (auto-park, out of the todo stream so
     reboost sweeps stop seeing it).
   - Append to desc: `AUTO-PARKED (stale-todo escalation): <N>
     reboosts to <assignee> without status change. Parked to backlog
     and escalated to Jeremy.`
   - Send a THREAD to Jeremy via the stale-escalation thread helper
     (new helper `_escalate_stale_todo_to_jeremy(item, assignee,
     boost_count)` — posts to the thread store with `from_session`
     unset so it hits Jeremy's inbox, body addressed to Jeremy, text:
     `"Stale-todo escalation: <id> — <title[:80]>. Assigned to
     <assignee>; <N> reboosts over ~<N*30>m without status change
     or pickup. Auto-parked to backlog. Investigate or reassign."`

5. **Behavior guarantees:**
   - `stale_escalated = 1` AND/OR `status != 'todo'` → the sweep's
     SELECT already excludes it (status filter), plus we add
     `AND stale_escalated = 0` to the SELECT as belt-and-suspenders.
   - A worker that FINALLY changes status (e.g. an hour after
     escalation) still clears the item from the sweep's view
     naturally.
   - If the human re-opens an escalated item (status back to todo),
     `stale_escalated` stays 1 — Jeremy should either reassign or
     reset the flag manually. The point of escalation is that the
     automatic loop gave up; a human must re-engage before the
     automatic loop retries.

6. **No changes to:**
   - First-mint nudge (`_notify_session_of_task` from POST /api/board).
   - Creator-of-stale notice (`_sweep_stale_todos` /
     `_notify_creator_of_stale`) — separate code path, pings the
     CREATOR not the assignee, Jeremy didn't flag it.
   - `_sweep_stale_doing` — separate, operates on `doing` not `todo`.

**Expected behavior after change:**
- Agent that cannot do a task will see progressively firmer language
  on each reboost telling it exactly what to do (status=backlog with
  reason). If it changes status, the loop stops immediately.
- Rate-limited / credit-limited agents stop getting pinged entirely
  (no wake, no token spend) until their limit clears.
- Items that go 4 reboosts without a status change get auto-parked
  and surfaced to Jeremy via thread, exactly once per item.

**Verify:**
- Python syntax ok (`python3 -c "import ast; ast.parse(open('amux-server.py').read())"`).
- Grep the server for `_sweep_stale_todo_reboost` and read the diff
  end-to-end — the only behavior change inside the loop is the
  skip-condition at the top and the branch replacing the
  `_notify_session_of_task` call near the bottom.
- Watch logs for `[stale-todo-reboost] skip` lines on the next tick
  if a rate-limited agent has stale todos.
- Confirm the escalation thread arrives when a test item sits past
  the flag threshold (can simulate by setting
  `AMUX_STALE_TODO_BOOST_FLAG_COUNT=1` for a session and letting a
  single ignored item escalate on the next sweep).

**Follow-up (NOT in this change):**
- Add agent-side convention doc in `_amux_shared.md`:
  "If a reboost arrives on an item you can't do, change status to
  backlog or discarded with a one-line reason — do NOT reply in-pane
  'can't do it'; the status change is the correct response."
  This is a shared-memory update, not a server change; Jeremy may
  want to add it himself.

---

## Plan for change: Codex sessions default to gpt-6-astra (Jeremy 2026-10-11) — DONE

**Trigger:** Jeremy: codex sessions in amux audit code and plan, so astra
(frontier model) is the right default across the board, not the general
workhorse gpt-6.1-sol.

**Scope:**
1. `_default_model_for_provider` (codex branch) returns `gpt-6-astra`.
2. `--model gpt-6-astra` injected at codex session start when CC_FLAGS
   lacks `--model`.
3. JS `providerDefaultModel` (codex branch) returns `gpt-6-astra`.
4. Per-org `.codex/config.toml` persistence:
   - EmberCRM: flipped from `gpt-5.6-luna` to `gpt-6-astra` (mcp_servers.codegraph block preserved).
   - RTG: already `gpt-6-astra`, left alone.
   - iSchedule: already `gpt-6-astra`, left alone.
   - ShareScore: top-level `model` key was absent; inserted `gpt-6-astra`.

**Live state (status after this change):**
- iSchedule-Audit-Codex: already running gpt-6-astra.
- ShareScore-audit: already labeled gpt-6-astra via server fallback.
- Ember-Audit-Codex: ACTIVE on gpt-5.6-luna. Not touching mid-task; will
  pick up astra on next natural restart, or Jeremy can `/model gpt-6-astra`
  live in that pane.
- RTG-Audit-Codex: idle on gpt-5.5. Can be live-swapped via tmux
  send-keys or restart; deferring to Jeremy's call.

**Verify:**
- `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` passes.
- Grep for `gpt-6.1-sol` finds no codex-flavored references (post-flip).

## Plan for change: Refresh Claude Code model list (Jeremy 2026-10-11) — DONE

**Trigger:** Jeremy pasted the current Claude Code model lineup. The old
dropdown names (claude-fable-5, claude-opus-5, 4-8, 4-7, 4-6, sonnet-5,
sonnet-4-6, haiku-4-5, dated 20251001) are now a mix of "latest" and
"older active" (new tiers landed above them). Keep all names that still
run, add new latest-tier entries, drop the stale dated variant.

**New Claude lineup (per Jeremy):**
- Fable 5.1 / Mythos 5.1 / Opus 5.5 / Sonnet 5.5 / Haiku 5.5 = latest
- Other active: Fable 5, Mythos 5, Opus 5/4.8/4.7/4.6/4.5, Sonnet 5/4.6,
  Haiku 4.5

**Scope (3 call sites):**
1. Settings dropdown Claude optgroup (L18901) replaced.
2. JS claudeModels array (L23115) replaced.
3. Drop existing `[1m]` variants and `claude-haiku-4-5-20251001` dated
   entry (not in Jeremy's new list). CLI aliases `sonnet`/`opus`/`haiku`
   preserved. If 1M variants are needed later, re-add.

**No default change:** `_get_default_model` returns `"sonnet"` fallback,
a CLI alias that auto-resolves to current latest sonnet. Already right.

**Verify:**
- `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` passes.
- Dashboard Claude picker shows the new tiers.
- No stray `claude-haiku-4-5-20251001` or `[1m]` strings in amux-server.py.

## Plan for change: Refresh Codex model list (Jeremy 2026-10-11) — DONE

**Trigger:** Jeremy pasted the current Codex model lineup. The old names
(gpt-5.5, o3, o4-mini, gpt-4o, gpt-4.1, gpt-4.1-mini) are being retired
and are already failing in flight. Ember-Audit-Codex's live config.toml
on disk already runs on gpt-5.6-luna; amux still offers only the dead
list.

**New lineup (lowercase-hyphenated form, as Codex CLI expects):**
1. gpt-6.1-sol (current workhorse) <- NEW DEFAULT
2. gpt-6-astra (frontier)
3. gpt-6-sol (previous gen workhorse)
4. gpt-6-luna (fast / affordable)
5. gpt-5.6-sol (older workhorse)
6. gpt-5.6-terra (older balanced)
7. gpt-5.6-luna (older fast)

**Scope (5 call sites in amux-server.py):**
1. `_default_model_for_provider` (L12567) returns the new default on `codex`.
2. `--model gpt-5.5` injection at codex session start (L13107) uses the new default.
3. Settings HTML `<optgroup label="Codex (OpenAI)">` (L18876) replaced with the 7 options.
4. JS `providerDefaultModel` (L22130) returns the new default.
5. JS `codexModels` array (L23080) replaced with the 7 options plus Default row.

**Behavior change:** new sessions created without an explicit model land
on gpt-6.1-sol instead of gpt-5.5. Existing session env files that already
pin a model stay as-is (ini is per-session, not server-pulled). No DB or
migration work. Any session still pinned to a retired name will fail at
Codex-side, not amux-side; owner should pick a new value in the settings
drawer.

**Verify:**
- `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` passes.
- Dashboard settings model picker shows the 7 new codex entries.
- `grep -nE 'gpt-(4|5\.5|4o|4\.1|o3|o4-mini)' amux-server.py` returns no
  codex-flavored matches (claude/gemini unaffected).



## Plan for change: Round 1 lockdown — creator required + PATCH field-lock + threads edit lock (Jeremy 2026-08-28) — DONE

**Trigger:** Two data-integrity incidents Jeremy hit:
1. Completion-notify hook exists but silently skips when `creator` is
   empty. Workers POST to PREBUILD/etc. with no `creator` body field →
   PREBUILD closes → poster never gets pinged → 6h15m blind wait.
2. An agent EDITED Jeremy's thread message and replaced the body with
   their reply. Server does not check ownership on message PATCH.

**Design principle (locked in):** server-set fields (X-Amux-Session
header → `posted_by_session`, `last_patch_by`) are the source of truth
for authorization; body-set fields (`creator`, `session`) are labels
that must be validated. Callers can lie about body; they can't lie
about the header the server writes.

**Round 1 scope (this commit):**

1. **Board POST `creator` required for agent callers.**
   If `X-Amux-Session` header is set:
   - If body has no `creator` → server auto-defaults it to the header.
   - If body `creator` ≠ header → 400 with hint (no falsification).
   - If body `creator` == header → accept.
   If header is absent (dashboard/Jeremy) → creator can be anything.
   Existing "server-routed" and blank creators on old items are legacy;
   no retro-enforce.

2. **Board PATCH poster-only field lock.**
   Fields open to ANY real session (unchanged): `status`, `desc`,
   `desc_append`, `session`, `tags`, `pinned`, `pos`, `due`, `due_time`.
   Fields locked to the poster (`posted_by_session == X-Amux-Session`)
   OR Jeremy (no header):
   - `title` — renaming another agent's item is falsification.
   - `creator` — hook-load-bearing; can't overwrite the audit trail.
   - `owner_type` — structural.
   - `gate` — the gate is a rule the poster set.
   - `org` — first-set immutable per existing rule; also locked here.
   Rejection returns 403 with `hint` naming the field + who owns it.
   Legacy items with empty `posted_by_session`: fall through (backward
   compat — those items pre-date AH-69). Explicit note in the hint.

3. **Threads PATCH message-edit lock.**
   On `PATCH /api/messages/<id>`: require `X-Amux-Session ==
   from_session` of the target message. Jeremy (no header) bypasses.
   Reject 403 with hint naming the correct message-owner.

**Explicitly NOT doing (Round 2/3 deferred per Jeremy):**
- Notes ownership marker, channel `<from>` verification, schedule owner
  check → Round 2 after end of week.
- Memory-global lock, skills ownership, /send attribution, DELETE
  /board poster-check → Round 3.
- One-shot retro-fire on the RP-* stragglers → not asked.
- No fallback `creator = creator || posted_by_session` in the notify
  hook — Round 1's mandatory creator makes new posts fire correctly.
  Existing empty-creator items stay silent (not asked to retro).

**Verification:**
1. Syntax check + reload.
2. Probe POST with header + no creator → auto-defaults, 201.
3. Probe POST with header + mismatched creator → 400 with hint.
4. Probe PATCH title on someone else's item → 403 with hint.
5. Probe PATCH status on someone else's item → 200 (unchanged).
6. Probe PATCH message body from wrong session → 403 with hint.
7. Commit.

Token budget: Jeremy at 98% today, reset 7pm CST. Doing minimum
work + probes, no fleet broadcast, no wake-ups.

---

## Plan for change: claim-on-pickup rule + schedules once/expr fix (Jeremy 2026-08-27) — DONE

**Trigger:** Jeremy asked for audit of (a) board watchdog script vs
(b) org CLAUDE.md board instructions. RTG-Research already diagnosed
the core gap and I confirmed it during the audit.

**Findings:**

- Both watchdog paths (SCHED-38 script + `_board_watcher` internal
  at L48245) fire only on `status='todo'`. Consistent behavior; not
  the bug.
- Every org CLAUDE.md/AGENTS.md (RTG, Ember, iSchedule, Cypra
  Master/PAA/EmailAgent) documents "PATCH to review on completion"
  but NONE document "PATCH to doing on pickup." The claim step is
  named only in the ping text itself. So agents work in `todo` for
  minutes → nudge sees "todo + idle" → re-pings → agent ignores
  because they know they're working it → token burn.
- Separate schedules bug: L44649-44653 silently upgrades
  `sched_type=once` to `recurring` when `schedule_expr` is set.
  `{"sched_type":"once","schedule_expr":"+2h"}` becomes an
  every-2-hours cron. Undocumented.

**Ship in this commit:**

1. Add rule #7 to `_MEM_CRITICAL_RULES` (inline, always-seen at
   session start): "Claim on pickup — PATCH todo→doing the moment
   you start. `todo` is the only re-ping-eligible state; `doing`,
   `review`, `backlog` are quiet."
2. Add a section to `_global.md` (fuller detail) documenting the
   state lifecycle: `todo → doing (on pickup) → review (on
   completion)`. Backlog for parked/not-now.
3. Add the RTG-Research paragraph (verbatim) to each org CLAUDE.md
   board section: RTG, Ember, iSchedule, Cypra/Master.
4. Fix POST /api/schedules: if caller explicitly passed
   `sched_type=once`, honor it (don't upgrade to recurring). Only
   auto-upgrade when `sched_type` wasn't specified.
5. Add hint on POST /api/schedules when the combination arms an
   ambiguous shape.

**Explicitly NOT doing:**
- Not touching the watchdog scripts' ping-eligibility logic — it's
  correct as-is (todo only). The behavior mismatch was on the agent
  side, not the substrate side.
- Not changing the stale-DOING sweep (fires on doing past 45m; has
  exemptions from earlier fixes; still worth signal).
- Not shipping a `claim` alias for `amux board doing <id>` — the
  `amux board claim` CLI already exists; agents just need to use it.

**Verification:**
1. Syntax check + reload.
2. Regenerate fleet MEMORY.md via POST /api/memory/global.
3. Spot-check a regenerated MEMORY.md shows rule #7 inline.
4. Probe POST /api/schedules with sched_type=once + schedule_expr
   → confirm once is honored.
5. Reply to Jeremy with a short summary.

---

## Plan for change: iOS Files download `_token` injection (Jeremy 2026-08-26) — DONE

**Trigger:** Jeremy on iOS mobile PWA: Files tab → Cypra/docs/personal/
<file>.xlsx → Download shows `{"error":"unauthorized"}` JSON. Works on
desktop; fails on iOS.

**Root cause:** `_fileDownload` builds the URL as
`API + '/api/file/raw?path=<encoded>'` and uses `fetch(url)` then a
blob → `<a download>` click. The fetch monkeypatch at L19828 adds
Bearer auth for same-origin URLs, and on desktop that path works
end-to-end. On iOS Safari, `<a download>` isn't reliably honored and
the click can fall through to a URL navigation — which hits
`/api/file/raw` WITHOUT the Bearer header and returns JSON 401.

**Fix (1-line JS):** wrap the URL with `_authUrl()` when setting
`dlBtn.dataset.url`, so it carries `?_token=<AUTH_TOKEN>` regardless
of whether the browser uses fetch or direct navigation. `_authUrl`
already exists (L19822) and the server's auth gate already accepts
`_token=` in the query string (L41079).

**Explicitly NOT doing:**
- Not changing the fetch path (it works when the browser honors
  `<a download>`).
- Not changing server auth semantics (already accepts _token=).
- Not auditing every other download button — this one is the reported
  case; others may or may not have the same shape, follow up if
  another instance surfaces.

**Verification:**
1. Syntax check + reload.
2. Confirm the URL now contains `_token=`.
3. Jeremy re-tries on iOS.

---

## Plan for change: Cypra-only-tools rule in critical rules (Jeremy 2026-08-26) — DONE

**Trigger:** Jeremy: a CD-* agent spent several minutes trying to
reach Notion when asked for latest notes. Only Cypra has Notion
access (by design); only Cypra sends outbound email on Jeremy's
behalf. Other agents should delegate — not attempt directly.

**Fix (two edits):**

1. Add 6th inline rule to `_MEM_CRITICAL_RULES` (short, always
   visible at session start):
   > **Notion + outbound email = Cypra-only.** Ask Cypra via board
   > (session `Cypra`); never scrape or invoke email tools directly.

2. Add a short section to `_global.md` with the concrete curl for
   posting a task to Cypra. Propagates via `_amux_shared.md`.

Regenerate fleet MEMORY.md via POST /api/memory/global to push both
edits to every session's on-disk copy in one wave.

**Explicitly NOT doing:**
- Not restricting Notion/email tools at the MCP layer — they aren't
  accessible in other sessions anyway; the failure was the agent
  trying alternative reach paths (web scrape, guessed URLs, etc.).
  The behavioral rule fixes that.
- Not shipping a wrapper skill (e.g. `/ask-cypra`) — nice-to-have
  but wait for evidence the rule alone isn't enough.

**Verification:**
1. Syntax check + reload.
2. Regenerate fleet MEMORY.md; spot-check RTG-ActCloudPortal + CD-CPAP
   see the new rule in their inline block AND the fuller section in
   _amux_shared.md.

---

## Plan for change: gated-todo idle-nudge suppression (AH-99, 2026-08-26) — DONE

**Trigger:** EmberCoreMigration filed AH-99. Idle-nudge (_board_watcher)
fired 10+ times on EAAC-34, a deliberately gated todo item that must not
start until an external c00 validation runs. Sub-agent declined every
time, then asked "is something wrong?" — trust-erosion cost. Board has
no way to express "parked/gated" — todo means "available to pick up",
and the nudge does its job on the information it has.

Recurring cost is nudge fatigue: if agents learn to ignore idle-nudges,
the mechanism loses signal quality on the calls that matter.
EmberCoreMigration's own AH-96/AH-97/AH-99 filings all trace back to
similar shape (silent behavior at boundary; agents can't observe).

**Fix (AH-99 suggestion #1 — cheapest, zero schema change):**

_board_watcher SELECT gets `desc` too. Filter out items whose:
- Title starts with `PARKED`, `GATED`, or `BLOCKED` (case-insensitive,
  boundary after) — matches EmberCoreMigration's `PARKED (post-c00) —`
  workaround.
- Desc has a line starting with `GATED:`, `BLOCKED-UNTIL:`,
  `BLOCKED-BY:`, `PARKED:`, `AWAITING:`, or `HOLD:` (case-insensitive).

Suppressed items still appear in the board UI and are still available
to work on — they just don't generate an idle nudge. Once the gate
clears, agent removes the marker and nudges resume normally.

**Explicitly NOT doing:**
- AH-99 suggestion #2 (new `blocked` status) — schema + hooks + status
  transition rules across the codebase. Overkill for a first cut.
- AH-99 suggestion #3 (`gated_until`/`blocked_by` field) — most
  expressive but most work; wait for evidence #1 isn't enough.
- Not suppressing the C4/promote-backlog or dependency logic — this
  only touches the idle-nudge signal to the assignee.

**Verification:**
1. Syntax check + reload.
2. Confirm EAAC-34 has a matching marker in title or desc; check dry-run.
3. Board watcher runs every 30s — verify next tick shows no nudge for
   the gated set.
4. Close AH-99 with fix summary (via desc_append, dogfooding again).

---

## Plan for change: C4 discard-tolerant single-audit completion (Ember-Research, 2026-08-26) — DONE

**Trigger:** Ember-Research reported C4 wedges targets in `review`
forever when ONE auditor discards its item (Ember-Audit-Opus48 standing
policy: discard ED/coordinator items as VOID-not-auditable — same as
RTG-Audit-Codex per AGENTS.md) while the OTHER closes with a verdict.
5 ECM items wedged ~1h tonight (ECM-9/13/14/15/16); Ember-Research had
to hand-adjudicate each. Recurs on every future coordinator umbrella
item.

Root cause in `_auto_verify_from_audit_pair` (~L9883):
- Discarded audit's own PATCH event → returns None at status check
  (`if audit_item.get("status") not in ("done","verified","review")`).
- Verdict-holder's PATCH event → finds nothing at the `WHERE status
  != 'discarded'` clause when looking up the sibling → returns None.

**Fix (Ember-Research's proposal — cleanest of the two considered):**

Extend `_auto_verify_from_audit_pair` to handle discarded state on
either side:

1. Allow discarded status on the trigger audit (self).
2. Include discarded in the sibling lookup (drop the WHERE filter).
3. Branch on the (my_state, other_state) matrix:
   - Both have verdicts → existing pair logic (unchanged).
   - One discarded + one verdict → apply the verdict alone, tag
     `[single-audit]` in cascade note (surviving_id=... discarded_id=VOID).
   - Both discarded → leave in `review`, `send_text` to master session
     (`<org>-Research`) explaining both auditors voided — needs
     human/master call. Idempotent via existing target status check.

Alternative Ember-Research considered and rejected: stop minting audit
pairs for ED-wrapper items server-side. Wrapper-ness detection is
fuzzy (title prefix ED: isn't universal). Discard-tolerant C4 is
cleaner and doesn't require server-side wrapper heuristics.

**Explicitly NOT doing:**
- Not changing what an auditor discards (that's the auditor's policy
  and it's correct).
- Not making single-audit paths silent — cascade note includes the
  `[single-audit]` tag and both audit ids so provenance is visible.
- Not shortcutting the both-discarded case to any auto-status — a
  target where BOTH auditors voided likely means the target is itself
  a wrapper and probably should be discarded, not verified. Kick to
  master.

**Verification:**
1. Syntax check + reload.
2. Confirm 5 wedged ECM items would now clear if their audit pair
   were re-evaluated (retroactive check via dry-run).
3. Post reply board item to Ember-Research with fix summary.

---

## Plan for change: desc_append mode on board PATCH (AH-97, 2026-08-26) — DONE

**Trigger:** EmberCoreMigration filed AH-97 with 2 real data-loss
incidents tonight — EAAC-29 lost a 37-row per-column classification
table, EAAC-36 self-clobbered its submission summary. Both from the
same footgun: `PATCH /api/board/<id>` with `desc:` silently replaces.
The MEMORY.md inline rule I added 3 days ago in d5d15ada mentioned it
but a sub-agent under load didn't consult the reference.

**Fix (AH-97 suggestion #1 — cleanest):**

Add `desc_append: "..."` body key on board PATCH.
- If present AND `desc:` also present → 400 with hint (ambiguous).
- If present alone → server reads current desc, writes back
  `current + "\n\n" + append` atomically inside the same PATCH.
- Empty/whitespace `desc_append` → no-op (return current row).
- Absent → current behavior unchanged.

Same-request atomicity is important: race with a concurrent PATCH
would otherwise clobber whichever wins the write. Simple solution:
compute inside the existing set_clauses loop, right before UPDATE.

**Update the inline critical rule** in MEMORY.md's autogenerated
essentials block so agents learn about desc_append at the same point
they learn about the replace footgun. Regenerate fleet MEMORY.md via
POST /api/memory/global to propagate.

**Explicitly NOT doing (yet):**
- AH-97 suggestion #2 (reject/warn on shrink >N%): more surface,
  threshold tuning risk. Ship #1 first; if a 3rd incident happens
  because an agent forgets desc_append exists, add #2.
- Not changing existing `desc:` semantics — backward compat.

**Verification:**
1. Syntax check + reload.
2. `curl PATCH ... -d '{"desc_append":"NEW"}'` → row's desc becomes
   `existing + "\n\n" + NEW`.
3. `curl PATCH ... -d '{"desc":"X","desc_append":"Y"}'` → 400 hint.
4. Regenerate MEMORY.md fleet-wide; spot-check RTG-ActCloudPortal
   sees the updated rule.
5. Reply to amux-helper via board close (creator on AH-97).

---

## Plan for change: watchdog for dormant schedules (AH-96 ask #3, 2026-08-24) — DONE

**Trigger:** AH-96 root cause was SCHED-219 sitting at run_count=0 for
9 days with no visibility. Existing CATCH-UP log (AH-59) fires only for
already-enabled schedules that miss a slot; it doesn't catch the
"created enabled=0, never flipped, forgotten" class.

**Fix:** small daily sweep — schedules with `run_count=0` AND
`created` older than 3 days → Pushover alert to Jeremy once per
schedule. Idempotent via a new column `dormant_alerted_at`.

Scope of alert-target class:
- `enabled=0 AND run_count=0 AND created < now - 3d` — the AH-96 shape.
- Not also touching enabled=1 (already-scheduled but silently missing
  runs) — the CATCH-UP log covers that once they DO fire. Adding a
  parallel enabled=1 dormancy alert would double-fire during normal
  first-fire runs of new schedules.

Design:
- ALTER TABLE schedules ADD COLUMN dormant_alerted_at INTEGER DEFAULT 0.
- New `_sweep_dormant_schedules()` scheduled daily via `schedule_job`
  (interval=86400, initial_delay=600 so it doesn't fire immediately
  on server start).
- For each matching row, `_pushover_alert()` with title
  "amux dormant schedule: <SCHED-N> <title>" and body naming last
  update + age. Set `dormant_alerted_at = now` to suppress re-fire.
- Env override `AMUX_DORMANT_SCHEDULE_DAYS` (default 3, range 1-30).

**Explicitly NOT doing:**
- Not a UI badge — the alert is enough; dashboard schedule column can
  be enhanced separately if Jeremy asks.
- Not auto-enabling dormant schedules — that's Jeremy's judgment;
  substrate should surface, not decide.
- Not adding the parallel "enabled=1 but never fired" check —
  first-fire covers itself; wait for concrete evidence of a second
  failure class before adding surface.

**Verification:**
1. Syntax check + reload.
2. Confirm SCHED-219 no longer qualifies (run_count now =1).
3. No other schedules currently qualify (need to grep) — if any do,
   Pushover fires; that's the point.

---

## Plan for change: add missing Claude models to picker dropdowns (Jeremy 2026-08-24) — DONE

**Trigger:** Jeremy notes amux picker doesn't list all current Claude models.

**Current gap** vs live Anthropic lineup:
- Missing entirely: `claude-opus-5` (+ `[1m]`) — the current top-tier Opus.
- Missing 1M variants for Fable 5 and Sonnet 5 (existing entries have plain
  `claude-fable-5` and `claude-sonnet-5` but no `[1m]` — inconsistent with
  the Opus 4.6/4.7/4.8 pattern which lists both).
- Haiku entry uses only the dated form `claude-haiku-4-5-20251001`; add the
  short form `claude-haiku-4-5` too (matches how other tiers are listed).

**Three call sites to update in lockstep:**
1. L17733 settings default-model dropdown (HTML `<option>` list).
2. L19342 per-session model picker (HTML `<option>` list).
3. L21924 JS `claudeModels` array (dynamic dropdown used elsewhere).

Also NOT adding: `claude-mythos-5` (Project Glasswing only, not general).

**Verification:**
1. Syntax check.
2. Hot-reload; open the settings dropdown, verify Opus 5 + new [1m] entries render.
3. Commit.

---

## Plan for change: move _global.md out of MEMORY.md into topic file (RTG-Research bug report, 2026-08-23) — DONE

**Trigger:** RTG-Research reports the composed portion of MEMORY.md
(_global.md + container_preamble) crowds it past Claude Code's 200-
line load cap. Fleet measurement: 26 of 46 MEMORY.md files exceed
200 lines. RTG-ActCloudPortal is 409 lines with agent index only
19 lines — composed portion is ~390 lines and eating the load budget.
Worker session cited (all 13 RTG sessions share the container HOME)
correctly refused to violate either the hook or the do-not-remove
marker; sessions are unable to update memory indexes.

**Fix (RTG's option 3, refined):**

1. `_write_claude_memory` writes _global.md content to
   `<memory_dir>/_amux_shared.md` (leading underscore = amux-managed,
   agents should not edit).
2. MEMORY.md format becomes:
   ```
   <agent session content>

   <!-- amux:session-memory -->

   # amux platform essentials (autogenerated — details in _amux_shared.md)
   - Threads = Jeremy inbox ONLY. Agent→agent posts return 403.
   - Board = task handoffs/status. Channels = 2-way agent↔agent. Notes = docs.
   - Full inter-session API + rules: `_amux_shared.md` (read at start of session).

   # ─ Container context (docker:<X>) ─
   <per-session container preamble>
   ```
3. `_capture_claude_memory_changes` gains new-format handling; keeps
   old-format marker split for backward compat during the migration
   wave (existing MEMORY.md files transition on next `_write_claude_memory`).
4. First-call migration: on first _write for each session, if the
   existing MEMORY.md is old-format, extract agent portion via existing
   split logic, then write in new format.

**Explicitly NOT doing:**
- Not writing to any `~/.claude/CLAUDE.md` — risks trampling Jeremy's
  host global CLAUDE.md; safer to use amux-owned topic file.
- Not changing _global.md editing UX — Jeremy still edits it in one
  place, we just write it to a different destination.
- Not exempting the auto-block from any hook — no such hook exists in
  our substrate; the "hook" RTG-Research references is Claude Code's
  built-in 200-line load cap and its auto-memory advisory text.

**Verification plan:**
1. Syntax check + hot-reload.
2. Trigger _write for a single test session (probably a Cypra session
   already ~465 lines) → verify new-format MEMORY.md is <60 lines +
   _amux_shared.md exists with _global.md content.
3. Cycle through 3-4 more sessions, spot-check for parse regressions.
4. Fleet-wide roll: next session-start of each session naturally
   overwrites with new format via existing _write_claude_memory hook.
5. Reply to RTG-Research on channel confirming ship + measured effect.

**Not shipping until RTG-Research acks proposal.**

---

## Plan for change: measure cold-age from Jeremy's last message (Wattco followup #3, 2026-08-22) — DONE

**Trigger:** Wattco caught a re-ping degrades-signal shape: current
cold-cap uses "we sent last message's timestamp" as the age reference.
So an agent gets the cold-thread nudge, re-pings the human, its ping
becomes the last message (timestamp = now), and the item flips back to
thread-active for another 14 days. Repeat forever = permanent
exemption via ritual re-pinging into a void. Wattco: "the signal
degrades from 'someone is waiting' to 'someone is still typing'."

**Fix:** measure age from `last message with from_session != own_session`
(Jeremy's last touch, or any non-own-session), not our last message.
When Jeremy has been silent >N days, the thread is cold regardless of
how recently the agent re-pinged. When Jeremy actually replies, his
message becomes the "last message" and the exemption releases anyway
(agent now owes an action), so the exemption boundary stays right.

Fallback: if the thread has NO non-own-session messages ever, use the
thread's `created` timestamp as the reference age.

**Explicitly NOT doing:**
- Not counting consecutive cold-cycles as a distinct escalation tier —
  the age-from-Jeremy fix collapses that class into the existing
  cold-thread signal without adding cycle-tracking state.
- Not touching the 2× threshold escalation tier — same rule.

**Verification:**
1. Syntax check + hot-reload.
2. Dry-run against current board — cold-set count should stay ~similar
   (~19) since real Jeremy-silence hasn't changed.
3. Reply to Wattco on channel.

---

## Plan for change: age-cap the thread-ref exemption (Wattco followup #2, 2026-08-22) — DONE

**Trigger:** Wattco measured the prior thread-ref fix board-wide: 66 of
146 doing items exempted via thread-ref; 20 of those reference threads
silent >14 days. "We sent last" has drifted from "waiting" to
"abandoned" — permanent exemption becomes badge-drift in a new place.
Wattco has skin in the game: CW-364/367 are 2 days into exactly this
pattern and Wattco explicitly wants a nudge when the thread goes cold,
not silence.

**Fix (minimal):**

1. `_stale_doing_awaiting_external` returns an `exempt_kind`:
   - `"board"` — open item in different session (exempt)
   - `"thread-active"` — we replied, thread within cold cap (exempt)
   - `"thread-cold"` — we replied but thread silent >N days (NOT exempt;
     but treat as a distinct nudge shape)
   - `None` — no exemption applies
2. Age-cap default: 14 days (Wattco's suggestion). Tunable via
   `AMUX_STALE_DOING_THREAD_COLD_DAYS`.
3. New nudge helper `_notify_stale_doing_cold_thread(session, id, title,
   thread_id, thread_silent_days)` sends text: "Your reply on {tid} has
   been silent {N}d — re-ping the human or close this item. Not a
   general staleness nudge; the escalation itself has gone cold."
   Distinct from generic stale nudge so the agent knows what to do.
4. Reuse `stale_doing_nudged_at` flag semantics — cold-thread nudge
   fires once per stall like the normal one.

**Explicitly NOT doing:**
- Not making the age-cap per-thread configurable — one global default is
  fine, agents can escalate individually if 14d is wrong for a case.
- Not distinguishing the escalation tier (2× threshold to master) for
  cold-thread — same rule, same escalation, just different text.

**Verification:**
1. Syntax check.
2. Hot-reload.
3. `slog` shows `exempt (thread-active)` vs `exempt (thread-cold)` vs
   `not exempt` on next sweep tick.
4. On next tick, one of the 20 cold-thread items gets a
   cold-thread-specific nudge (verify text).
5. Reply to Wattco on channel.

---

## Plan for change: extend stale-DOING exemption to thread-refs (Wattco followup, 2026-08-22) — DONE

**Trigger:** CD-WattcoAccMigration verified the first fix against its own 4
items and reported it partially misses: CW-364/CW-367 reference T-169 (a
thread), not a board item, and are legitimately blocked on a client answer
that only Jeremy can obtain. Wattco explicitly refused to name-drop AH-90
into their descs to game the exemption ("teaches every agent that the way
past the reaper is to name-drop an open ticket"), which is exactly right —
we need a real signal, not a cheat.

**Fix (small, additive):** extend `_stale_doing_awaiting_external` to also
treat thread-id refs (`T-###`) as an exempt signal, but only when the
thread's most-recent non-discarded message's `from_session` equals the
item's `own_session`. Semantic: "we sent last" ⇔ "waiting on the other
side" ⇔ legitimate block. When Jeremy replies to the thread, the last
message's from_session flips to '' and the exemption releases — the
correct nudge shape (agent now owes an action).

Verified against T-169: last message is FROM CD-WattcoAccMigration, so
CW-364/CW-367 will exempt.

**Explicitly NOT doing:**
- Not adding an explicit `BLOCKED-EXTERNAL` marker (Wattco's option 2).
  Requires convention adoption; option 1 needs zero convention and uses
  existing thread data.
- Not exempting on any thread reference — the sender-of-last-message check
  is what makes this a real signal instead of a badge.

**Verification:**
1. Syntax check.
2. Hot-reload.
3. `slog` shows `[stale-doing] CW-364 CD-WattcoAccMigration — exempt (awaiting T-169@Jeremy)` on next sweep tick.
4. Reply to Wattco on channel confirming ship.

---

## Plan for change: stale-DOING sweep — awaiting-external exemption (AH-90/91/92/93/94/95, 2026-08-22) — DONE

**Trigger:** cluster of 6 board tasks (AH-90, 91, 92, 93, 94, 95) plus a
CD-WattcoAccMigration channel note. The stale-DOING sweep I shipped
2026-08-20 (45m threshold + 90m escalation) over-fires on the standard
nightly-billable-notes protocol shape: source item posts a CP-* handoff
to Cypra-PAA and MUST stay in `doing` until Cypra closes it with an
outcome code (CW-288 rule — never self-close). Every 45m the sweep nudges
the assignee; every 3 remedies the sweep suggests are forbidden for this
class (bump = pure noise, back-to-todo breaks the confirmation loop,
to-review misrepresents unconfirmed as finished). AH-90 shows 142 of 152
board-wide doing items trip the threshold across 12 sessions.

Wattco's verbatim proposal: "a 'waiting on external input' state, or
exempting items whose closure is owned by another session, would solve
the whole class."

**Fix (small, targeted):**

Add an exemption inside `_sweep_stale_doing` (~L6853):

1. SELECT now includes `desc` (currently only id/title/session/org/updated/flags).
2. New helper `_stale_doing_awaiting_external(desc, own_session, db)`:
   - regex `\b([A-Z][A-Z0-9]{0,8}-\d+)\b` against desc → set of referenced ids
   - if empty → return False
   - SELECT id, session, status FROM issues WHERE id IN (...) AND status IN ('todo','doing','review')
   - if any row's session != own_session → return True (with the ref id + session for log)
3. In the per-row loop, if `_awaiting_external` → `slog` and `continue`
   WITHOUT bumping flags. Next tick re-evaluates; when the referenced
   item closes, the sweep will fire normally (which is the correct signal —
   the block has been released and the item is now genuinely stale).
4. False-positive tolerance: over-exempt is OK (delayed nudge on unrelated
   ref), under-exempt was costing real churn. This is the right side to err on.

**Explicitly NOT doing:**
- Not raising the base 45m threshold — the sweep's original purpose (catch
  idle live agents holding doing items) still needs a tight threshold.
  Exemption addresses the false-positive class without weakening the signal.
- Not introducing an explicit `blocked_on` column — requires adoption across
  all writers, larger surface. Desc-scan heuristic captures the natural
  handoff pattern that's already universally written.
- Not touching AH-88's Cypra-PAA outcome-patchback drop — separate follow-up.
- Not re-enabling writeup_handoff_auto_mint (AH-89) — still disabled pending
  the 4-step hardening.

**One-shot cleanup after ship:**
Clear `stale_doing_nudged_at` and `stale_doing_escalated_at` on all currently-
doing items that now qualify for the exemption, so the fix takes effect
retroactively rather than waiting for next natural transition.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` (hot-reload).
3. Watch `slog` for `[stale-doing] ... skipped (awaiting <CP-###>@Cypra-PAA)` lines.
4. Confirm amux-helper's own trapped CID-* / CW-* / CCP-* items get no fresh nudge next tick.
5. Close AH-90..AH-95 with fix summary; reply on Wattco channel.

---

## Plan for change: audit-pair re-fire endpoint (AH-70, 2026-08-17) — IN PROGRESS

**Trigger:** RTG-Research filed AH-70. 7 items (RA-1057, 1062, 1063, 1065, 1074, 1077, 1081) are stuck in `review` with no audit pairs minted. Root cause is well-diagnosed by RTG: their original build-verifies (RV-530/536/537/539/552/558/565/566) all FAILed on a shared compile break; they closed each as `done, SUPERSEDED by RV-573` — no `VERDICT:` line — so `_auto_on_build_verify_close` (L8808) short-circuited at L8821 (`_extract_verdict` returns nothing → return). Meanwhile RV-573 (PASS) covered the whole batch but its title only names ONE target, so the close hook only re-fires for that one.

Deadline pressure: last gates before 8/31 rollout; Jeremy actively waiting.

**Fix (small, targeted):**

Add `POST /api/board/<id>/mint-audit-pair` — admin re-fire endpoint. Validates the target exists and is in `review`, then calls the existing `_mint_audit_pair_unguarded`. Follows the pattern of the existing `/api/board/<id>/claim` and `/api/board/<id>/run` endpoints. Small surface: one route, one internal call.

Then use it to mint pairs for the 7 named targets in one script — un-stall the batch.

**Reply to RTG-Research with:**
- Which items got minted (the 7).
- Going-forward contract: closing a superseded BV should include `VERDICT: PASS (superseded by RV-573)` — one line, and the close hook fires per-item as designed. That's a docs answer, not a code change.
- For the static-site class (RA-1081, RV-571 = CANNOT VERIFY / not-applicable): use the new endpoint. Considered adding `VERDICT: N/A` support but it's not worth the surface area for a rare case — one manual `curl POST /api/board/RA-XXXX/mint-audit-pair` is fine.

**Explicitly NOT doing:**
- Not adding `COVERS: <id> <id> ...` batch-BV support — larger surface area, and the per-item VERDICT contract solves the same problem simpler.
- Not weakening `_extract_verdict` to accept SUPERSEDED — verdict is signal, silence is silence.
- Not adding auth on the new endpoint yet — matches the other /api/board/<id>/* patterns which are open.
- Not fixing RA-1077's review→doing→review bounce that didn't re-trigger; the freshness rule at L8955 IS correct (BV was still fresh vs target update), the target simply never got a fresh BV to close.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. `curl -sk -X POST /api/board/RA-1057/mint-audit-pair` returns `{"action":"audit-minted","target":"RA-1057","audits":["RAC-...","RAO-..."],"auditors":["RTG-Audit-Codex","RTG-Audit-Opus48"]}`.
4. Fire for all 7. Confirm audit pairs land on RTG-Audit-Codex + RTG-Audit-Opus48 queues.
5. Reply on AH-70.

---

## Plan for change: board list respects limit/status/session + immutable poster audit (AH-69, 2026-08-17) — IN PROGRESS

**Trigger:** Cypra-PAA filed AH-69 with two board-API bugs found during CS-224/CS-225 investigation:

1. **`session=` on a board item is not proof of actor.** POST /api/board accepts session+creator verbatim from body — any process can claim any session. My own self-test of the creator-notify hook (CS-224) exercised exactly this: amux-helper POSTed with `session=CD-SurfPrep, creator=Cypra-PAA` and the completion nudge read "done by CD-SurfPrep" when CD-SurfPrep never touched the item. Board history can attribute actions to sessions that took none.
2. **`GET /api/board` silently omits an existing item AND ignores query params.** CS-225 returns 200 on direct GET but is absent from the list (`_load_board` L6711 caps done/discarded at the most-recent 100 by `updated DESC` — CS-225 is `done` but older than the top-100). Meanwhile `?limit=5000`, `?status=done`, `?session=X` are all ignored — only `done_limit` and `org` are read.

**Fix — two changes, minimal surface:**

### Change A — GET /api/board query-param support (fixes bug #2)

Extend the handler (L42677) to accept:
- `limit=N` (alias for done_limit; wins if both provided). Caps at 10000. `limit=0` = unlimited.
- `status=X` → filter to that status. Skips the UNION math — one WHERE clause. Works with any status including custom columns.
- `session=X` → filter to that session's items. `session=none` = unassigned.
- Existing `done_limit` + `org` unchanged.

_load_board grows a `status_filter` and `session_filter` param. When either is set the UNION branch is skipped in favor of a single filtered SELECT (respecting the current org_clause).

### Change B — immutable poster audit columns (fixes bug #1)

Add two DB columns:
- `posted_by_session TEXT` — from `X-Amux-Session` request header on write, empty when absent (e.g. dashboard host writes).
- `posted_by_ip TEXT` — from `self.client_address[0]` (loopback = 127.0.0.1 for local, gateway IP for cloud).

Both are set at row-CREATE time and NEVER updated by PATCH. If a PATCH mutates the item, we still capture `patched_by_*` — third column `last_patch_by TEXT` populated from the same header on every PATCH, overwritten each time.

Wire:
- POST /api/board: set posted_by_session + posted_by_ip on INSERT.
- PATCH /api/board/<id>: set last_patch_by on UPDATE.
- Include all three in _load_board SELECT + single-item GET response.
- Migration: existing rows get NULL — that's fine, audit only works forward.

Completion-notify message: prefer `last_patch_by` (or `posted_by_session` for a create-based close, though these are rare) over body's `session` field. Fall back to body's `session` with a "(claimed session — actor identity not verified)" hint if header was absent.

**Explicitly NOT doing:**
- Not adding auth on POST/PATCH — orchestration legitimately needs to write on behalf of other sessions.
- Not rejecting body's `session=X` when it doesn't match header — that's the orchestration use case (me writing as amux-helper with session=CD-SurfPrep is legitimate).
- Not migrating existing rows' posted_by — no way to reconstruct.
- Not making the audit columns dashboard-visible in this change (just API-visible). Dashboard column can come later.
- Not touching CP-508 — Cypra verified it already used direct GET as authoritative and stands. Her note about "session= isn't authoritative" is what the new audit columns give her.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. GET /api/board?status=done → should include CS-225 (all done items, no cutoff).
4. GET /api/board?session=CD-SurfPrep → only CD-SurfPrep items.
5. GET /api/board?limit=5000 → up to 5000 items.
6. POST /api/board with X-Amux-Session:foo header → GET back shows posted_by_session=foo.
7. PATCH from a different session → last_patch_by reflects that session.
8. Reply to AH-69 with the fixes.

---

## Plan for change: stale-doing sweep — nudge stalled assignee + escalate to master (Jeremy 2026-08-20 17:49) — IN PROGRESS

**Trigger:** Jeremy noticed RTG agents (ActCloudPortal + ActAS) idle. RTG-Research diagnosed: "sessions alive (heartbeat fine) but not picking up doing-status items. The board watchdog also cannot see doing items — known gap." Research had to manually restart both.

Current gap: `_task_guard` at L9739 nudges idle sessions WITHOUT a doing item. If session HAS a doing item, it assumes "already tracking, will close it" and does NOTHING even after hours of no progress. Matches Research's diagnosis exactly.

Symmetric to yesterday's `_sweep_stale_todos` (creator-notify when assignee never picks up a TODO). This is the DOING-side sweep: assignee-notify when a DOING item sits with no progress.

**Fix (mirrors _sweep_stale_todos pattern):**

1. **Schema:** new `stale_doing_nudged_at INTEGER NOT NULL DEFAULT 0` column on issues. Timestamp of last stale-doing nudge; skip re-nudge if `nudged_at >= item.updated` (nothing has changed since we already alerted).

2. **Helper `_notify_stale_doing(session, item_id, title, age_min)`:**
   - `send_text` tmux inject to the assignee's pane
   - Message: `"Stale DOING: {id} — {title[:80]} hasn't been updated in {age}m. If you're still working: bump `updated` by PATCHing anything. If stuck: PATCH back to `todo` and post a board item to your org's Research session (or amux-helper for substrate issues). If done: PATCH to `review`."`
   - Also `slog` for observability

3. **Sweep `_sweep_stale_doing()`** — registered via `schedule_job(interval=300, name="stale_doing_sweep")`:
   - Query: `status='doing' AND owner_type='agent' AND session non-empty AND updated < now - STALE_DOING_MIN` (default 45 min, configurable AMUX_STALE_DOING_MIN 15-240).
   - Filter to items where `stale_doing_nudged_at < updated` (haven't already nudged for this stall).
   - For each: check assignee status via `is_running(session)`. If NOT running → skip (session_dead alerts handle it). If running (any status): nudge.
   - Set `stale_doing_nudged_at = now` on fire.

**Also — org-master escalation for deeper stalls** (per Research's "I had to restart them" pain):
- After 2 * STALE_DOING_MIN (default 90 min), ALSO ping the org's Research session with the same info: `"Worker session X has stalled on DOING item Y-99 for Nh. It's been auto-nudged twice with no bump."`
- Uses a separate flag `stale_doing_escalated_at INTEGER` to fire once per stall.
- Skip if session doesn't have a Research counterpart (`{org}-Research` env file missing).

**Explicitly NOT doing:**
- Not auto-restarting the assignee. Jeremy explicitly said Research "started restarting agents" — that's a decision the master should make, not the substrate. My sweep names the stall so Research (or Jeremy) can decide.
- Not touching the review/verified/done side — those transitions are healthy states.
- Not sweeping items with `session != creator` filter (like the todo sweep). A self-assigned doing item can still stall. Nudge the assignee regardless.
- Not adding Pushover to Jeremy. In-terminal nudge to the assignee + eventual Research ping is the escalation ladder; Jeremy only gets pinged if Research escalates via thread (existing rule).

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload (schema migration on startup).
3. Live test: create a `doing` item, backdate `updated` 60 min. Wait for next sweep tick. Confirm assignee's pane gets the nudge, `stale_doing_nudged_at` gets stamped.
4. Verify re-nudge doesn't fire on next tick (nudged_at ≥ updated).
5. Bump item's `updated` (any PATCH), backdate 100 min, confirm escalation to Research fires.
6. Reply to Jeremy with what shipped.

---

## Plan for change: coordination-artifact filter on audit-mint (AH-86, 2026-08-20) — IN PROGRESS

**Trigger:** RTG-Research filed AH-86 as follow-up to AH-77 (id-prefix filter). RA-1133 was a `BYPASS AUTHORIZED` process directive that auto-minted FOUR audit pairs on review re-entries (RAO-7794/7800/7807/7809, all voided — wasted auditor cycles). Same class as AH-77's RV-*/RP- filter but the trigger is TITLE-prefix (RA prefix is legit workspace, only the title marks it as coordination).

**Fix (small, mirrors AH-77 shape):**

Add a title-prefix guard alongside the existing `_CONTROL_PLANE_PREFIXES` id-prefix guard. Place it inside `_mint_audit_pair_unguarded` (not just `_auto_mint_audit_pair`) so ALL mint paths benefit — review-entry hook, BV-pass sweep (AH-83), and manual re-fire endpoint (AH-70).

New constant:
```python
_COORDINATION_TITLE_PREFIXES = (
    "BYPASS AUTHORIZED",
    "PROCESS:",
    "ROUTING:",
    "TRACK:",
    "HELLO WORLD",
)
```

New check in `_mint_audit_pair_unguarded` before the auditor-session existence check:
```python
_ttitle = (target_item.get("title") or "").strip().upper()
if any(_ttitle.startswith(p.upper()) for p in _COORDINATION_TITLE_PREFIXES):
    return None
```

Case-insensitive title-prefix match (upper on both sides). List can grow — one-line addition per new prefix. Any real work item legitimately starting with one of those tokens can be re-titled or use an explicit escape hatch (out of scope; not needed for the observed noise).

**Explicitly NOT doing:**
- Not adding a `no_audit` body field. Title convention is what RTG-Research already uses; adding a flag doubles the surface area and doesn't help retroactively.
- Not filtering `_extract_target_id` — that's fine; it's about "can this be a target?" (RA-1133 legitimately IS a target for cross-reference purposes), not "should it get an audit pair?".
- Not touching the manual re-fire endpoint's own guardrails — if a human EXPLICITLY POSTs `/mint-audit-pair` for a coordination artifact, they get 409-no-mint via the existing fresh-pair check or the new title-prefix filter, whichever hits first.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. POST a test review-status item titled `BYPASS AUTHORIZED: test` with session=RTG-ActAS org=RTG. Call `/mint-audit-pair` — expect no-mint with hint.
4. Same for `PROCESS:`, `ROUTING:`, `TRACK:`, `HELLO WORLD` prefixes.
5. POST a normal titled item ("Fix X"), confirm audit pair still mints.
6. Cleanup + reply on AH-86.

---

## Plan for change: stale-todo creator alert (Jeremy 2026-08-19 04:14) — IN PROGRESS

**Trigger:** Jeremy — "if a board task is not grabbed in 15 mins, the board needs to tell the agent that created it it's stale so the creator can investigate what's going on with the assignee (might be remote agent, might be missing pushes, etc)."

Fits cleanly alongside this morning's `_notify_creator_of_completion` (creator notified on task done) — this is the SYMMETRIC "creator notified on task stuck". Fills the gap where an assignee that never picks up sits invisible to the creator.

**Fix (small, follows established patterns):**

1. **Schema:** new column `stale_notified INTEGER NOT NULL DEFAULT 0` on issues. Append to existing migration loop at L5847 area (same pattern as `notified` and this morning's `creator_notified`).

2. **Helper `_notify_creator_of_stale(creator, item_id, title, assignee, age_min, assignee_hint)`:**
   - Same shape as `_notify_creator_of_completion`.
   - Atomic 0→1 CAS on `stale_notified` to prevent double-fire under races.
   - Best-effort `send_text` background thread.
   - Message: `"Stale task: {id} — {title[:80]} assigned to {assignee} is still 'todo' after {age_min}m. Assignee may be stuck / offline / missing push. Hint: {assignee_hint}. Check `amux board show {id}`."`
   - Include assignee's session state as hint: `not-running`, `running-CC_REMOTE`, `running-idle`, `not-a-session` (per `_is_real_session`).

3. **Sweep `_sweep_stale_todos()`:**
   - Query: agent-owned items in `todo` older than 15 min, not self-assigned, creator is real session, `stale_notified=0`.
   - For each, gather assignee state via `is_running()` and env-file CC_REMOTE check.
   - Call `_notify_creator_of_stale`.
   - Wrap in try/except so a single row failure doesn't stop the sweep.

4. **Register:** `schedule_job(_sweep_stale_todos, interval=300, name="stale_todo_sweep", initial_delay=60)`. Every 5 min → alerts fire within 15-20 min of task creation. Matches Jeremy's threshold.

**Explicitly NOT doing:**
- Not firing for creator = Jeremy / creator empty / creator = 'threads' (the Jeremy-thread-delivery creator string) — those go to Jeremy via existing Pushover paths.
- Not firing for creator == assignee (self-assigned housekeeping — noise).
- Not re-alerting if item cycles todo → doing → todo. The retake helpers (`_notify_session_of_retake`) handle cycles; the stale flag stays 1 once fired.
- Not touching the sweep for stale doing/review (out of scope — Jeremy specifically said "not grabbed in 15 mins", i.e. still todo).
- Not adding Pushover — creator gets in-terminal notification via `send_text`, matching the completion-notify pattern. Jeremy's phone doesn't get pinged for every stale task.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload (schema migration runs on startup).
3. Manually POST a test task from amux-helper to a session that ignores it. Wait 15 min. Confirm amux-helper's pane gets the stale alert.
4. Verify `stale_notified` flips to 1 in DB (SELECT after alert).
5. Verify no re-alert on subsequent sweeps (flag stays 1).
6. Cleanup test items.

---

## Plan for change: TWO live cross-org data leaks (Jeremy 2026-08-19 via M-4528) — IN PROGRESS

**Trigger:** Cypra-PAA in M-4528 flagged 2 security exposures stuck 40 days behind a routing bug. Both confirmed real, both LIVE right now.

### Bug #1 — /logs mount exposes every org's session transcripts to every other org

**Root cause:** amux-server.py L1660 — `cmd += ["-v", f"{CC_LOGS}:/logs:rw"]` mounts the entire `~/.amux/logs/` dir (RW) into every org container. Comment at L1658 explicitly acknowledges this was Phase 2c temporary work: "Phase 9 will restructure to ~/.amux/logs/<product>/<session>.log with a per-org subdir mount." Phase 9 never shipped.

**Scope (confirmed by docker exec):**
- 59 log files, 288MB
- Every org container (iSchedule, EmberCRM, RTG, all CD-*, Cypra, ShareScore, Scorpio) sees the same /logs with all 59 files
- These are FULL session transcripts — contain everything an agent typed/received, including any OAuth tokens the agent debugged, API keys, client PII in agent chatter, cross-client work details
- **Nullifies every skill-deny-list win.** An EmberCRM agent (Zoho-denied) can `cat /logs/CD-SurfPrep.log` and read every Zoho API call SurfPrep has made.

**Fix (code, no bounce):**
Change `_ensure_org_container` to mount only THIS org's own session log files, not the whole dir. For each session in `spec["sessions"]`, bind-mount `~/.amux/logs/<session>.log` to `/logs/<session>.log` (RW). Touch the log file on host if missing so the bind-mount doesn't create a directory. Don't mount the parent `/logs/` dir at all.

Applies only to NEW container spawns. **Existing running containers keep the wide mount until recreated** — Jeremy's call on when to bounce.

### Bug #2 — notes API has no access control; "ACCESS RESTRICTED" is comment-only

**Root cause:** amux-server.py L41692-L41702 — GET /api/notes/<name> reads the file with zero check. The `infra-credentials-structure.md` note starts with "! ACCESS RESTRICTED — This page is for Scorpio and Cypra-family agents only" as PROSE. Server never parses it.

**Scope:** any agent can `curl -H "Authorization: Bearer $AMUX_TOKEN" $AMUX_URL/api/notes/infra-credentials-structure`. Cypra reported iSchedule-Data hit it accidentally, saw ShareScore/DAL infrastructure details.

**Fix (code, hot-reload):**
Introduce a machine-readable ACL marker: `<!-- amux-acl: session1, session2, ... -->` in the note content (comma list, wildcards `*` allowed). GET/POST/PATCH/DELETE handlers scan the first 2KB for the marker. If present AND caller has X-Amux-Session set AND that session doesn't match the ACL → 403. Dashboard (UI token) and localhost bypass (matches the existing `_check_auth` shape). Add the marker to `infra-credentials-structure.md` immediately.

**Explicitly NOT doing in this pass:**
- Not recreating containers (Jeremy's call — bounces every agent).
- Not disclosing prior transcript exposure (past reads can't be undone; forward-only enforcement).
- Not adding per-session directory hierarchy under /logs (matches the eventual Phase 9 shape but bigger change).
- Not touching listing endpoint `/api/notes` — it returns names + sizes but not content; the ACL only gates content access.

**Verification (both fixes):**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload (fixes #2 immediately).
3. #1: create a fresh org container, exec into it, confirm `/logs/` shows only that org's session files.
4. #2: `curl -H "X-Amux-Session:CD-SurfPrep" /api/notes/infra-credentials-structure` → 403.
5. #2: same call with `X-Amux-Session:Cypra` → 200.
6. #2: dashboard access (UI token) → 200 regardless.
7. Reply to Cypra on the board with a summary of what was fixed vs what needs Jeremy's action (bounce).

---

## Plan for change: thread reply-to-parent context in agent board task (Jeremy 2026-08-19) — IN PROGRESS

**Trigger:** Jeremy screenshots — he was in a long CD-AirCom thread, went back to reply to an older message (M-4608, ~20 min old) about GIT setup + READYTOSHIP. His reply body was just "Yes Keep digging in to this one" — the "this one" only makes sense with M-4608 as context. The delivered board task (CA-97) shows Jeremy's reply text but does NOT include what M-4608 said. Agent has to guess or manually fetch.

Root cause: `_deliver` (L40851) builds the preamble from the incoming message alone. Its `parent_id` (the message being replied to) is in the DB but never referenced in the delivered text.

**Fix (one added block, ~15 lines):**

Inside `_deliver`, before building `preamble`, look up `msg_row["parent_id"]`. If non-empty and points at a real message in the same thread, fetch and prepend as a "Context — replying to <M-id> (<sender>, <time>):" block quoting the parent body. Truncate if very long (>1200 chars).

Fires for BOTH the board-task path (`preamble` variable) AND the blocking-inject path (the shorter `send_text` message).

**Explicitly NOT doing:**
- Not fetching the WHOLE conversation history — parent-only. Deep threads would blow context.
- Not adding this when parent_id is empty (root reply). No parent = no need.
- Not truncating parent body aggressively — 1200 chars covers most agent replies; longer gets `…[truncated]` with a hint to `amux threads show <T-N>`.
- Not showing parent context when parent_id happens to equal the just-delivered mid (shouldn't happen but defensive).
- Not touching the reply-CLI hint — `amux threads reply <mid> "…"` still targets the just-delivered message (Jeremy's), which is correct — the agent's reply is to what Jeremy said, not to the parent.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. Live-test: create a small test thread with 3 messages (A, B, C). Reply to A. Confirm the delivered board task shows A's body as "Context — replying to <A-id>" before Jeremy's reply.
4. Reply to Jeremy noting the fix + when he'll see it (next thread message he sends).

---

## Plan for change: batch-BV audit-mint sweep (AH-83, 2026-08-19) — IN PROGRESS

**Trigger:** Third audit-mint starvation in three days (AH-70 → AH-78 → AH-83). RTG-Research demanded a permanent fix. Same failure shape each time:

- Worker item enters `review`
- `_auto_mint_audit_pair` sees no BV yet → mints a fresh BV (holds audits)
- That BV closes with FAIL / gets superseded / emergency-bypassed
- Eventually a DIFFERENT BV (batch build, or fresh emergency-bypass BV) closes with PASS
- `_auto_on_build_verify_close` only cascades to the TITLED target of THAT BV
- Other review items whose commits are covered by the same batch build sit orphaned

I've been manually re-firing via the AH-70 endpoint. That doesn't scale — 3 incidents in 3 days.

**Permanent fix (one added sweep in `_auto_on_build_verify_close`):**

When a BV closes with PASS/PASS-WITH-WARNINGS, extract commit hashes from its desc (`\b[0-9a-f]{7,40}\b`), then sweep for other `review`-status items in the SAME org whose title or desc contains any of those hashes, and mint their audit pairs.

Guardrails:
- Only fire on PASS/PASS-WITH-WARNINGS (existing gate stays).
- Only sweep items in same org as the BV.
- Only sweep items in `review` status.
- Only sweep items whose session is a worker (skip *-Audit-*, *-Research, *-Remote per existing `_auto_mint_audit_pair` rules).
- Skip control-plane prefixes (already covered by `_CONTROL_PLANE_PREFIXES` when `_mint_audit_pair_unguarded` is called).
- `_mint_audit_pair_unguarded` already has a fresh-pair short-circuit, so re-fires against items already covered are safe no-ops.
- Cap the sweep at N items per BV close (say 20) so a malformed desc listing 100 hashes can't runaway-mint.

Regex is `\b[0-9a-f]{7,40}\b` — matches git short hash (7+) through long hash (40). False-positive risk: any 7+ hex string in a desc could match (ETag values, IDs). Filtering by both org and review-status contains the blast radius, but I'll also add a common-word blacklist (`abcdef1`, `1234567` etc.) if it becomes an issue.

**Explicitly NOT doing:**
- Not touching `_auto_mint_audit_pair` (the review-entry path). Its logic is correct for the first-time BV lookup; the gap is the LATE cascade.
- Not adding a commit-covered-by-BV lookup table. That's the cleaner architecture per RTG's ideal, but requires schema + backfill. Regex-match on desc is 90% of the win at 5% of the cost.
- Not sweeping on FAIL closes. FAIL bounces the titled target back to `doing`; other targets should keep waiting for their own build.
- Not sweeping across orgs. A BV closing in RTG doesn't cascade to Ember review items.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. Set up: create two review items with the same commit hash in their titles. Mint a BV for one, close BV with PASS. Confirm BOTH get audit pairs (the titled target via existing path, the sibling via new sweep).
4. Confirm sweep skips items already having fresh audit pairs.
5. Confirm sweep skips FAIL closes.
6. Reply on AH-83 with fix + note that RA-1131 was already re-fired via endpoint.

---

## Plan for change: case-insensitive session filter on board list (AH-82, 2026-08-19) — IN PROGRESS

**Trigger:** RTG-Research filed AH-82 from RR-1730. Items were filed with `session=RTG-PreBuild` (correct env name) but an agent polled `?session=RTG-Prebuild` (lowercase 'b'). SQL match is `session = ?` = case-sensitive, so the query returned empty → 2 false stall alarms + 2 emergency bypasses + one false Pushover to Jeremy.

Yesterday's AH-79 (write-side validation) already prevents future typo POSTs — `POST /api/board -d '{"session":"RTG-Prebuild"}'` for an agent item would now 400 with `did_you_mean:["RTG-PreBuild"]`. But the READ side (`?session=X` filter) is still case-sensitive, which is exactly what tripped this: the item was written with the correct name, the poll used the wrong case.

**Fix (one line, three call sites in `_load_board`):**

Change SQL from `i.session = ?` to `LOWER(i.session) = LOWER(?)` at all three occurrences of `session_clause` in `_load_board` (L6746 status-filter branch, plus L6772 + L6796 UNION-branch queries — I added them all yesterday under AH-69). SQLite LOWER() is ASCII-only which is exactly what we want here (session names are ASCII kebab-case, no unicode risk).

The `session=none` branch stays `IS NULL` — unchanged.

Not changing:
- Single-item GET `/api/board/<id>` — lookup by id, session doesn't matter for retrieval.
- Notify/send paths — those use the item's stored session verbatim (which is now guaranteed canonical case by AH-79 for new agent items).
- POST/PATCH validation — already enforces canonical case via AH-79's roster check.

Combined effect: **writes require canonical case** (AH-79), **reads accept any case** (AH-82). Symmetric-enough to make the RR-1730 shape impossible going forward.

**Explicitly NOT doing:**
- Not making ALL filters case-insensitive (org, status). Those have well-defined canonical values (`RTG`, `todo`, `verified`) and case-insensitive matching there would mask real typos rather than help.
- Not normalizing session-case in the DB on read — the stored value stays as-written. Match at query time only.
- Not auto-fixing old items with weird casing — write-side validation is now enforcing forward.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. Create test item with `session="RTG-PreBuild"` (real). Query `?session=RTG-prebuild` (any case). Should return the item.
4. Query `?session=RTG-PreBuild` (correct case) — should still return the item (backward compat).
5. `?session=Cypra-PAA` and `?session=cypra-paa` should return the same set.
6. Reply on AH-82.

---

## Plan for change: validate session field on board POST/PATCH (AH-79, 2026-08-19) — IN PROGRESS

**Trigger:** Cypra-PAA filed AH-79 with a real cost — 3 items (PAA-1/2/3) posted with `session="PAA"` (typo for "Cypra-PAA") sat invisible for 25-36 days because no real session's queue matched. One of them (PAA-3, filed under CP-568) is a client deliverable now 36 days overdue.

Any typo in `session=` creates a silent dead-letter queue.

**Fix (three narrow changes):**

1. **New helper** `_suggest_close_sessions(name, k=3)` — uses stdlib `difflib.get_close_matches` against the current `~/.amux/sessions/*.env` roster. Returns up to 3 close-match suggestions.

2. **POST /api/board** (~L42682): after parsing `session`, if `session` is non-empty AND the effective `owner_type` is `"agent"` (default when session is set), require `_is_real_session(session)` OR an explicit escape hatch. Otherwise 400 with:
   ```json
   {
     "error": "unknown session",
     "session": "PAA",
     "did_you_mean": ["Cypra-PAA", "Cypra"],
     "hint": "The session '<name>' has no env file in ~/.amux/sessions/. If you really want to pre-create a task for a session that doesn't exist yet, pass allow_unknown_session:true."
   }
   ```
   Human-owned items (`owner_type=human`) skip validation — `session` there is a label (e.g. Jeremy, a client name), not a routing target.

3. **PATCH /api/board/<id>** (~L42863): if the PATCH body contains `session` AND the new value is non-empty AND the effective `owner_type` will be `"agent"`, apply the same validation. Reassigning to a typo is the same failure shape.

**Explicitly NOT doing:**
- Not validating `creator` — that field is often a human name ("Jeremy") or an external tool ("nightly-billable-notes.py") that isn't a session.
- Not building a full "unrouted items" view/alert — the rejection at write time prevents the class from recurring. If historical dead-letters need discovery, that's a separate one-off script (Cypra can widen her search or I can dump `SELECT * FROM issues WHERE session NOT IN (...)`).
- Not auto-fixing existing PAA-1/2/3 or Cypra's CP-568 — she owns those; my fix prevents future ones.
- Not blocking session="" (that's legit "unassigned").

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. `curl POST /api/board -d '{"title":"test","session":"PAA","owner_type":"agent"}'` → 400 with `did_you_mean: ["Cypra-PAA", ...]`.
4. `curl POST /api/board -d '{"title":"test","session":"Cypra-PAA","owner_type":"agent"}'` → 201.
5. `curl POST /api/board -d '{"title":"test","session":"PAA","owner_type":"agent","allow_unknown_session":true}'` → 201 (escape hatch works).
6. PATCH an existing agent item's session to a typo → 400.
7. Reply on AH-79 with the fix + note that CP-568 is Cypra's routing job.

---

## Plan for change: audit-mint filter + CC_REMOTE start guard (AH-77, 2026-08-18) — IN PROGRESS

**Trigger:** RTG-Research filed AH-77 with two substrate findings from today's hello-world round-trip (RR-1660):

(a) `_auto_mint_audit_pair` fires on RV-*/RP-* coordination items (RV-544, RV-597, RP-16 cited). Those are build-verify + connectivity items that auditors can only VOID — pure noise on the audit queue. Add the two prefixes to `_CONTROL_PLANE_PREFIXES` so the mint hook skips them (same mechanism already handles RD/RR/RAC/RAO/AH/AW).

(b) RTG-PreBuild's env file has `CC_REMOTE=1` + a `do not start locally` note in `CC_DESC`, but the flags were advisory — someone (Jeremy) started it locally and got a Linux impostor answering for what should be a Windows-only session. Add a hard refusal in `start_session` mirroring the existing `CC_ARCHIVED=1` guard.

**Fix (two tiny changes):**

1. `_CONTROL_PLANE_PREFIXES` (L8602) — add `"RV"` and `"RP"`. Effect:
   - `_auto_mint_audit_pair` skips them at L8928 (`if tprefix in _CONTROL_PLANE_PREFIXES: return None`).
   - `_extract_target_id`'s `_scan` skips them at L8694 as target candidates — bonus, since RV/RP aren't legitimate targets of anything else either.

2. `start_session` (L11121) — add after the `CC_ARCHIVED` check:
   ```python
   if cfg.get("CC_REMOTE") == "1":
       return False, ("session is remote-only (CC_REMOTE=1) — runs on a remote box "
                      "that polls the amux board; do not start it locally. "
                      "See _{name}.env for details.")
   ```
   All existing callers already handle `(False, msg)` refusals (archived, blocked, invalid name). Auto-restart / wake / snapshot loops will now correctly refuse local restart of remote sessions — matches the intent that already exists elsewhere (e.g. `_auto_archive_idle` L47482 explicitly skips CC_REMOTE=1).

**Explicitly NOT doing:**
- No `--force` override on start_session — Jeremy can edit the env file if he genuinely needs a local start (rare; better to have the friction).
- No host-match check (`CC_REMOTE_ALLOW_HOST=<hostname>`) yet — the simple refusal solves the observed failure. If a future incident shows we need per-host lockdown, add then.
- Not touching the auto-archive-idle CC_REMOTE=1 skip — already correct, unrelated.
- Not adding RV/RP to the escalation-gate regex (L42736 already lists RP; RV isn't relevant there).

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. `curl -X POST /api/sessions/RTG-PreBuild/start` → 200 with `{"ok":false,"error":"session is remote-only..."}`.
4. `curl -X POST /api/sessions/CD-SurfPrep/start` → still succeeds (not CC_REMOTE).
5. PATCH a hypothetical RV-999 to review; confirm no audit pair mints (mint would appear in cascade as `{"action":"audit-minted",...}` on the PATCH response — expect NO such block).
6. Reply on AH-77.

---

## Plan for change: unblock hook — miss on C3/C4 direct-DB paths (Ember-Research 2026-08-17 late) — IN PROGRESS

**Trigger:** First real-world test of this morning's `_promote_backlog_when_dep_completes` missed. EA-39 flipped verified via C4 auto-apply ~19:4x; EO-12 (backlog, `BLOCKED_BY: EA-39`) was NOT promoted. Manual promotion at ~20:00.

Ember-Research submitted two hypotheses. Verified:
- **H1 (correct):** the unblock hook is called from the PATCH `/api/board/<id>` handler's cascade block only. C4's `_auto_verify_from_audit_pair` (L9217) does a DIRECT `db.execute("UPDATE issues SET status=...")` + `db.commit()` — bypasses the PATCH handler entirely. Same shape in C3's `_auto_apply_adjudication` (L9109) and `_try_route_rd` (L8437, RD→done). Any status flip that reaches verified/done via those paths never fires my unblock sweep.
- **H2 (wrong):** the "BLOCKED_BY unmet:" annotation line. Regex-tested: `_BLOCKED_BY_RE` (`^[ \t]*BLOCKED_BY:\s*...$`) requires `BLOCKED_BY:` (colon immediately after), so it correctly skips `BLOCKED_BY unmet:` and matches the actual `BLOCKED_BY: EA-39` line. Ember-Research's guess there was incorrect. Confirmed via Python REPL — will note in the reply so they update their mental model.

**Fix (three sites, one call each):**

Add a `_promote_backlog_when_dep_completes(target_id, new_status, db)` call after each direct-DB status write in:

1. `_auto_apply_adjudication` (C3, ~L9114) — right after `_board_changed()`, when `new_status in ("verified","done")` (verified is the only new_status this function produces; the FAIL path writes "doing"). So just guard on `if new_status == "verified"`.
2. `_auto_verify_from_audit_pair` (C4, ~L9222) — same shape; guard on `if new_status == "verified"` (the FAIL/FAIL path writes "doing").
3. `_try_route_rd` (~L8440) — the RD flip is always to `done`. Fire the sweep unconditionally after the commit. Rare that anything BLOCKED_BY's an RD, but consistent semantics is worth the two lines.

The PATCH-handler call I added this morning stays as-is — it covers manual PATCHes, `POST /api/board/<id>/mint-audit-pair`, and any other direct-PATCH path.

Wrap each call in try/except so a sweep failure never blocks the hook it's attached to. Log unblocked ids the same way (`[unblock] promoted X ...`).

**Explicitly NOT doing:**
- Not refactoring the three direct writes to route through the PATCH handler (larger change, risk of behavior drift).
- Not extracting a "commit status change + fire all downstream hooks" helper (nice long-term but out of scope; this fix is 3 x 5 lines).
- Not touching the regex — verified correct.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. Live test: create A + B where B is `BLOCKED_BY: A`, then flip A → verified via a mechanism that goes through C4 (audit pair PASS/PASS). Confirm B promotes to `todo`.
4. Reply to Ember-Research with (a) H1 confirmed and fix shipped, (b) H2 disproved with regex evidence, (c) how they can grep the server log if they get filesystem access later.

---

## Plan for change: auto-unblock backlog on dep-verified (Ember-Research 2026-08-17) — IN PROGRESS

**Trigger:** Ember-Research reports this recurred for EO-11 today (BLOCKED_BY: EA-35, EA-35 verified ~17:5x, EO-11 stayed backlog until manual promotion ~30 min later). Same shape as ECI-31 on 2026-08-12. Two occurrences = pattern.

**What exists:** `_try_route_rd` (L8320) parses `BLOCKED_BY:` at MINT time. If any listed dep isn't verified/done, child starts in `backlog`. Once minted, NOTHING listens for dep completions — the child stays backlog forever until a human/orchestrator notices and PATCHes it. Ember-Research's ask: hook C4/verdict path to sweep backlog items and promote when the dep set is fully satisfied.

**Fix (one helper + one call site):**

1. **`_promote_backlog_when_dep_completes(completed_id, new_status, db) -> list[str]`** — new function co-located with `_try_route_rd`. When completed_id flips to verified/done:
   - `SELECT id, desc, session, title FROM issues WHERE status='backlog' AND deleted IS NULL AND desc LIKE '%BLOCKED_BY%{completed_id}%'` (SQLite LIKE is fine — false positives get filtered by the regex parse below, and the query stays cheap since backlog is small).
   - For each candidate: re-parse `BLOCKED_BY` line with `_BLOCKED_BY_RE`; skip if completed_id isn't actually in the dep list.
   - Check ALL deps in the list: if any is still not-verified-and-not-done, skip. If all met, `UPDATE ... SET status='todo', notified=0` (reset notified so assignee gets pinged fresh).
   - Call `_notify_session_of_task` for the assignee.
   - `slog("[unblock] promoted <id> to todo — all deps now met (triggered by <completed_id> → <new_status>)")`.

2. **Wire into PATCH `/api/board/<id>` handler** at L42933 (same try/except block as C3/C4 cascades). Call after the existing cascade attempts:
   ```python
   _unblocked = _promote_backlog_when_dep_completes(bid, _new_status_final, db)
   if _unblocked:
       cascaded = cascaded or {"action": "unblocked"}
       cascaded.setdefault("unblocked", []).extend(_unblocked)
   ```

**Explicitly NOT doing:**
- No recursion: promoting X won't cascade to Y-blocked-by-X in the SAME PATCH. Y will promote when whatever verified X flips X's own dep chain — every terminal-flip triggers its own sweep.
- No sweep on non-terminal transitions (todo→doing, doing→review) — BLOCKED_BY semantic per `_try_route_rd` L8385 gates on `verified`/`done` only.
- No re-mint of dropped notifications: the notified flag reset handles it, no separate machinery.
- No changes to the mint-time logic in `_try_route_rd`.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. Live test: create parent P (todo → verified), create child C with BLOCKED_BY: P (mints backlog), verify P → check C flipped to todo AND assignee got the ping.
4. Reply on Ember-Research's board item.
5. Also: check via SQL that no false positives — a backlog item with BLOCKED_BY: OTHER-1 must NOT promote when UNRELATED-1 verifies.

---

## Plan for change: agent-first memory ordering + description-field fix (AH-61 + AH-62, 2026-08-17) — IN PROGRESS

**Trigger:** CD-SurfPrep filed AH-61 + AH-62 with a beautiful root-cause chain:

- Composed MEMORY.md structure today: `container_preamble + _global.md + <MARKER> + <session>.md`. Prefix is 369+ lines, Claude Code loads ~200. Agent's own session-memory index (starting at line 370) NEVER loads → topic-file pointers orphaned → Skills protocol I broadcast via _global.md never reached them → they didn't know about POST /api/skills, kept doing it wrong.
- Same root cause: my _global.md advertises an `amux skills list|get|set` CLI that DOESN'T EXIST. The real path is POST /api/skills/<name>. The false CLI reference means anyone trying the "documented" way fails immediately.
- Real secondary bug: POST /api/skills body's top-level `description` field is silently dropped. There is no `description` column in the DB — description is always parsed from YAML frontmatter at read time. Sending a body with `{"content": "...", "description": "..."}` gains you nothing; the new content lands but the "how it's advertised" (from frontmatter) doesn't change. Silent-drop-of-payload-field is the worst API failure shape.

**Fix (three targeted changes):**

1. **Flip _compose_memory ordering** (L10317) — put session content FIRST, then marker, then composed prefix (container preamble + _global.md). Result: Claude Code's top-200 always includes the agent's own memory index, then whatever container-preamble/_global.md fits. Load budget stops silently orphaning agent memory.

2. **Update _capture_claude_memory_changes** (L10328) to handle BOTH old and new orderings gracefully during the one-write transition. Strategy: split on the marker, and identify the agent portion by "doesn't start with container-preamble anchor `# ─ Container context` or global-anchor `# Shared Context`". Whichever side matches those anchors is composed; the other side is the agent's.

3. **Reject POST /api/skills with silently-ignored fields** — if the request body contains `description` (or any other top-level key besides `content`), return 400 with an error naming the trap: "description lives in the YAML frontmatter of the content field. Extra top-level fields are ignored by the server — reject rather than silently drop. Put your description inside the content's frontmatter."

4. **Aggressive trim of _global.md** (from 405 lines → target ~180) — even after the ordering flip, keeping _global.md smaller is a good defense. Chopping targets:
   - Remove the FALSE `amux skills` CLI references (they don't work).
   - Compress "Writing to Jeremy" from 161 lines to ~30 (rule + one example, not paragraph after paragraph).
   - Consolidate "amux inter-session API" — the 150-line dump is mostly bash examples. Trim to the essential 3-4 commands; move detail to a `/skill:amux-cli` slash command that agents can invoke on demand.
   - Merge "Skills — how they work, how to add one" with the corrections above; drop the fictional CLI section.

**Explicitly NOT doing:**
- Not fighting Claude Code's built-in "MEMORY.md too big" warning — the ordering flip solves the underlying orphaning, which is the actual damage. The warning is Claude Code's, not amux's, and it correctly points at file size.
- Not adding a description column to the skills table — description-from-frontmatter is fine, we just need to reject the misleading API shape.
- Not touching per-session <session>.md files — they're agent-owned.

**Verification:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
2. `touch amux-server.py` → hot-reload.
3. Wake CD-SurfPrep, watch its composed MEMORY.md — session-memory content should be at the TOP.
4. POST /api/skills with a stray `description` field → 400 with clear message.
5. Reply on AH-61 + AH-62 with the fixes + answer CD-SurfPrep's three questions.

---

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

## Plan for change: Thread message body — link color white (2026-10-05, Jeremy) — DONE

**Trigger:** Jeremy, 2026-10-05: "When agents send me links they are blue, I cant see them on the black. Can we make all the links in threads WHITE like the text."

**Root cause:** The main dashboard `<style>` block has no global `a {}` rule. The only one in the file (L14877 `a{color:var(--green);...}`) lives inside the `/release-notes` page's style block and does not apply to the main dashboard. So `<a>` tags inside thread message bodies fall back to the browser's UA default (blue, visited=purple), which is unreadable against the dashboard's near-black bg.

`linkifyOutput()` (L25556) emits `<a href="..." target="_blank" rel="noopener noreferrer">URL</a>` with no inline style. Its only call site is L31459 in `_tRenderMsg` — the thread message body div — so a thread-scoped CSS rule covers every anchor it emits.

**Change:**
1. Add class `thr-msg-body` to the message body div at L31459 (currently inline-styled, no class).
2. Add scoped CSS rule after `.notes-preview a:hover` (near L17989) mirroring the existing pattern for `.notes-preview a` and `.md-content a` and `.overlay-body a`:
   ```css
   .thr-msg-body a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
   .thr-msg-body a:hover { opacity: 0.75; }
   ```
   `color: inherit` → takes the parent div's `color:var(--fg)` → matches body text exactly, no new color constant.

**Why not change `linkifyOutput` directly:** keeps styling out of the HTML-emitting function — same reason the file-link / md-link spans use `.file-link { ... }` class-scoped rules. If a future caller uses `linkifyOutput` outside threads, no inherited style surprise.

**Why not change the global `a{}` rule or add one:** too broad — would recolor every anchor on the dashboard (breadcrumbs, hidden overflow menus, etc.). Scoped rule is the least-invasive fix.

**Out of scope:** `.file-link` and `.md-link` spans in the same body use `color: inherit` only inside `.overlay-body`. Elsewhere they inherit from the surrounding div (which is `var(--fg)`), so they already match body text. Not touching them.

**Verification steps:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` — syntax OK.
2. Reload dashboard, open any thread with an agent message containing a URL → link renders white (same as body text), underlined.
3. Hover → slight opacity dim.
4. Mobile check: 375px wide, link still readable, 44px tap target preserved (anchor doesn't shrink).
5. `git add amux-server.py && git commit` with `fix(dashboard):` prefix.

**Rollback:** `git revert <hash>` — pure CSS/class change, no data/behavior effect.

---

## Plan for change: O — tighten ESC auto-mint gate (AH-115, 2026-10-09) — DONE

**Trigger:** RTG-Research filed AH-115 — RA-1689 and RA-1693 sat split-stuck in `review` ~13h because the C4 split-verdict → ESC auto-mint path refused to fire. The 24h-cooldown gate inside `_auto_mint_escalation` (L10426-10432) uses `title LIKE ?` with `f"%{target_id}%"` — so any Research followup whose title mentions the target id (RR-2404 "RA-1689 pivot: ACPSAS side done..." etc.) tripped the gate as a "prior ESC," blocking the real ESC mint.

**Precedent:** The POST-handler escalation gate at L45088-45096 was ALREADY fixed for this exact pattern (T-89 incident, RR-694 mis-tagged as prior ESC for RA-785) — it uses `f"ESC-{target_id}%"`. The internal mint gate is the twin and should match.

**Change:** one line in `_auto_mint_escalation`:
   - L10431: `(now - 86400, f"%{target_id}%")` → `(now - 86400, f"ESC-{target_id}%")`
   - Comment updated to point at the POST-handler cousin.

**Why just the title pattern:** closed-status exclusion (2026-08-14) is already there and correct. Session LIKE check (`-Research` OR `-Reviewer`) is already there. Only the title-LIKE needs tightening to the canonical ESC title shape.

**Verification steps:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` — syntax OK.
2. Confirm the fix: next time a split verdict closes on a target that has a Research followup matching `%target_id%` in title but NOT starting with `ESC-`, ESC mint fires.
3. For RA-1689, RA-1693: already handled manually (RA-1689 force-verified, RA-1693 flipped to doing by RTG-Research). No retroactive mint needed.
4. Commit with `fix(server): ESC auto-mint gate uses ESC-{target}% not %{target}% (AH-115)`.

**Rollback:** `git revert` — single-line condition tightening.

---

## Plan for change: A+B+C+M — C3/C4 cluster bundle (2026-10-08, Jeremy GO) — DONE

**Trigger:** Four separate substrate gaps collected over 2026-10-01..07, all in the C3/C4 audit-chain neighborhood of amux-server.py. Ember-Research + ECM filed each; Jeremy green-lit the bundle 2026-10-08 09:30. Ownership split: amux-helper owns the server-CODE bundle; Ember-Research owns the EmberCRM CLAUDE.md edits (L caveat + completion-rule correction).

**A. `_try_route_rd` — minted child inherits RD.creator** (L9229 → L9333)

Problem: child inserted with hard-coded `creator='server-routed'`, so when the child hits terminal, `_notify_creator_of_completion` fails the `_is_real_session('server-routed')` gate silently; the planner (RD author) never hears about build outcomes.

Change:
1. L9268-9270 SELECT: add `creator` → `SELECT session, creator FROM issues WHERE id = ? AND deleted IS NULL`.
2. Capture `rd_creator = me_row['creator'] if me_row else ''` after the row-fetch.
3. L9333 INSERT: `rd_creator or 'server-routed'` instead of the literal.

Fallback preserves the legacy case where the RD itself has empty creator (header absent on the POST that created it); nothing regresses.

**B. `_auto_verify_from_audit_pair` — fire `_notify_creator_of_completion` on target close** (L10576)

Problem: C4 auto-verify closes the target via raw `db.execute('UPDATE issues SET status=?, desc=?, updated=? WHERE id=?', ...)` at L10746 (single-audit) and L10881 (pair-complete). This bypasses the PATCH handler at L45630 where `_notify_creator_of_completion` normally fires on terminal-transition. Result: the target's creator (the planner who routed the work) hears nothing when the C4 pair auto-closes verified. Three Ember-Research incidents.

Change:
1. L10614 SELECT: add `creator` → `SELECT id, title, status, desc, session, org, creator FROM issues WHERE id = ? AND deleted IS NULL`.
2. After each `db.commit()` following the UPDATE (L10749 single-audit, L10884 pair-complete), fire the creator-notify under the same conditions `_notify_creator_of_completion` uses in the PATCH handler:
   - `new_status` is a terminal (`verified` / `doing` → both of C4's outcomes; keep `verified` as terminal, `doing` is a retake and NOT terminal under existing rules → fire ONLY on `verified` to match the PATCH-handler's `_TERMINAL` set).
   - `target['creator']` is truthy, not equal to the closer, and `_is_real_session(target['creator'])`.
3. Closer label: `f"C4 ({aid}+{other['id']})"` for pair-complete, `f"C4 single-audit ({surviving_id}+{discarded_id}=VOID)"` for single-audit.
4. closer_note: `""` — the auto-apply note already lands in the item's desc; no separate note.

Idempotency: `_notify_creator_of_completion` already uses the atomic `creator_notified` CAS, so firing from both the PATCH handler and the C4 branch for the same transition is safe — only the first one wins.

**C. `amux threads finalize` CLI header** (L5486)

Problem: the CLI curl at L5486-5487 emits `-H 'Content-Type: application/json'` only. The PATCH handler at L43138-L43180 (Round 1 lockdown + 2026-09-09 hardening) rejects content-key PATCHes (`body`, `blocking`) without `X-Amux-Session` with 403. So every containerized `amux threads finalize` returns an error and the partial stays `working`; the reaper mints new ER-* / ... / M-* every ~30 minutes forever. Three dangling partials this week.

Change: one line at L5486. Add `-H "X-Amux-Session: $AMUX_SESSION"` to the curl.

**M. C4 pairwise SHA prefix-normalization** (L10818)

Problem: L10818 does raw string equality on the two audits' AUDITED-SHA values. When one auditor records 7-char (`b4489e4`) and the other 40-char (`b4489e40d4ecdbbbe58772a7a77b91852ebd5c6c`) of the SAME commit, the pairwise ER-508 fallback false-holds. Also happened 2026-10-01 (ECI-66), 2026-10-07 (3× — EAO-595/597/601 on RA-1684/RA-1685). The existing `_tip_match` closure (L9736-9737) already does prefix matching for audit-vs-tip, so the pairwise site is the only remaining raw-eq comparison in the C4 cluster.

Change:
1. Add module-level helper near `_tip_match`:
   ```python
   def _shas_prefix_match(a: str, b: str) -> bool:
       """Two SHAs match if one is a prefix of the other, both >= 7 chars.
       Short-vs-full of the same commit should not false-mismatch.
       Added for C4 pairwise compare (2026-10-08, Ember-Research recurrence)."""
       if not a or not b: return False
       if len(a) < 7 or len(b) < 7: return False
       return a == b or a.startswith(b) or b.startswith(a)
   ```
2. L10818: `_sha_a != _sha_b` → `not _shas_prefix_match(_sha_a, _sha_b)`.

Min-length 7 guards against the degenerate "sha starts with hex digit X" false-match; 7 chars is `git rev-parse --short` default.

**Verification steps:**
1. `python3 -c "import ast; ast.parse(open('amux-server.py').read())"` — syntax OK.
2. Smoke: PATCH an item through `review` with a parent-ED creator set; verify minted child has `creator=<parent-creator>` not `'server-routed'`.
3. Smoke: simulate a C4 pair close with target creator ≠ assignee; verify creator gets pinged on verified.
4. Smoke: `amux threads finalize <mid> "test"` from inside a container; expect 200, not 403.
5. Smoke: two audits with 7-char vs 40-char AUDITED-SHA of same commit; verify no sha-mismatch hold.
6. Commit with `fix(server):` prefix listing A+B+C+M.

**Rollback:** `git revert <hash>` if any smoke fails. All four changes are additive-or-condition-widening; nothing changes existing passing-case behavior.
