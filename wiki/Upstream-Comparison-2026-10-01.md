# Upstream comparison — 2026-10-01 (research cycle 2)

Second research cycle against `git@github.com:mixpeek/amux` (first was `Upstream-Comparison-2026-08-19.md`). Trigger: Jeremy stood up a Rust eval server (`https://amux-eval.j3software.co:8824`) and asked whether we should migrate.

**Headline decision (2026-10-01):** DO NOT migrate. Stay on our Python fork, add multi-user support, selectively backport a few upstream ideas. Revisit in 6 months when upstream tags v1.0 and gains a stable branch. Rationale captured in §9.

## 1. Context — what prompted the cycle

- Jeremy wants other team members to interact with projects alongside him. Currently threads are hard-coded to Jeremy's inbox.
- Jeremy's stated original driver: "don't fall too far behind upstream."
- That driver was reversed by the pulse data (§8) — upstream ships 70+ commits/day. "Catch up" is not a real state; "merge forever" is the only state.

## 2. What upstream is

- `git@github.com:mixpeek/amux` — a 4-crate Rust workspace: `amux-core`, `amux-server` (axum + rusqlite/r2d2), `amux-cli`, `amux-dashboard` (vanilla JS PWA + service worker; build.rs bakes static assets).
- 133 API modules under `crates/amux-server/src/api/mod.rs`.
- Docstrings cite "PYTHON-PARITY port" and reference the retired `amux-server.py` by line number. Upstream was built by porting a ~65K-line single-file Python original to Rust. **Our fork is the Python original on a divergent branch.**
- Dashboard HTML carries a literal "EXTRACTED from retired Python server's inline DASHBOARD_HTML" comment — confirms the Python side is retired upstream.

## 3. Messages model — the headline difference

Upstream's `Message` is a durable entity (RR-0010, Invariant 29). File: `crates/amux-core/src/message.rs`.

- `MessageTarget` enum: `Worker(id) | Group(id) | Human`. One addressing primitive covers steering, mentions, task discussion, offline commands.
- `DeliveryState`: `Queued → Delivered → Acknowledged → ActedOn`. Each later state carries a UTC timestamp; `ActedOn` can name the `TaskId` it caused. `advance_delivery` enforces forward-only (409 on backwards move) — the record is audit trail.
- Group fan-out: one child `Message` per member, each with its own `Queued` row ("five members means five delivery records, not one optimistic 'sent'" — verbatim).
- Delivery timing: `AtTurnBoundary` by default; `Immediate` only for Cancel/Pause/Resume. The command carries only `MessageId`; the body is resolved from `_amux_messages` at delivery time. The docstring explicitly disses the Python original: *"The Python system lost pending steering text on every restart because the text lived in the delivery pipe."*
- API: `/api/messages` POST, `GET /{id}`, `POST /{id}/ack`, `POST /{id}/acted`, `GET /accountability`.

Our fork splits the same conceptual space across **three primitives** with server-side rules:

- **Threads** = Jeremy's inbox only. Agent→agent thread posts return 403; a thread body matching `\b<KnownSession>:` → 400.
- **Channels** = agent↔agent two-way chatter. Upstream also has channels (same JSONL shape under `~/.amux/channels/`) — one of the few places the two systems agree on the primitive, not just the problem.
- **Board** = task handoffs todo→doing→review→done. Watchdog re-pings `todo` ~15m. No forward-only delivery state machine, no per-recipient fan-out record.

Semantic gap: upstream's single `Message` with Worker/Group/Human + forward-only `DeliveryState` collapses our threads/channels/board handoff triad into one durable entity with real delivery accounting. Our enforcement wins (hard 403/400 on misuse) are social rules upstream encodes in the type system.

## 4. Feature matrix

| Category | Upstream (Rust) | Our fork (Python) |
|---|---|---|
| Storage | SQLite via rusqlite + r2d2 pool; ULID IDs | SQLite + JSONL fallbacks; mixed IDs |
| Transport | axum 0.8 + tokio | stdlib `http.server`, single-file |
| Isolation | tmux sessions `amux-wrk_<ulid>` only (RR-0032) | **Docker per-org** (`~/.amux/orgs/*.yml` → container, mounts, creds) |
| Dashboard | Vanilla JS PWA + service worker; build.rs bakes static | Inline HTML/CSS/JS in `amux-server.py` |
| Memory | `_amux_memories` with versions, soft-delete, `expect_version` optimistic concurrency (409 not LWW), scope visibility (private/group/global/org) | Markdown files under `~/.claude/projects/.../memory/`; no version/scope ADT |
| Scheduler | Dual-scheduler shadow mode via `AMUX_RS_SCHEDULER=1`; CRUD + audit always live | Python-only, cron-like (see §6) |
| MCP | `/api/mcp` registry; `ready` computed from credentials-existence; writes `~/.amux/mcp.json` only | Seed file, no readiness probe |
| Orchestration | `/api/orchestrate/plan` — voice transcript → routing plan, roster-validated | Human-authored board posts; no planner |
| Needs-input | `/api/needs-input` triage queue, rank-ordered, snoozes in `prefs` | Dashboard-driven, no consolidated endpoint |
| Realtime | `api/sse.rs` + chat_worker SSE | SSE with 10s pings / 18s zombie / `_onClientResume` |
| Auth | Shared `~/.amux/auth_token`; `?_token=` for EventSource | Same shape (ported from us) |
| **Notes** | **Absent** — no `notes.rs`, no `/api/notes` (eval server returns 404, confirmed 2026-10-01) | First-class primitive, pull-based docs |
| Projects / Workers | "project" = top-level org-equivalent (pure logical grouping, no container surface); workers = tmux sessions keyed to a project | Our `~/.amux/orgs/*.yml` + agent sessions — same concept with Docker/mount/cred baggage |

## 5. What upstream built better (worth stealing selectively)

- **Messages as durable entities with forward-only `DeliveryState`.** Audit trail by design. Group fan-out produces per-recipient rows.
- **Versioned memories with `expect_version` → 409.** Not LWW. One `visible()` predicate covers private / group / org / global.
- **Dual-scheduler shadow mode.** Both schedulers run; only one fires; audit from both. We could copy this pattern for ANY cutover, not just a Rust port.
- **Needs-input triage endpoint.** One ordered pane of everything waiting on a user. We have the primitives, not the single surface.
- **MCP registry with real readiness.** `ready` = "credentials actually on disk." Would have caught the 09-19 Google-connector regression.
- **Doctrine-encoded code.** Every file cites its RR / Invariant / incident ID. Our substrate doctrines live in `wiki/Substrate-Doctrines.md`; theirs are docstrings on the functions they govern.
- **133 purpose-built API modules.** brex / dictation / email_intel / chatgpt_app / torrents / telegram / standing_approvals / dependency_audit / planning / policy / reconciliation / interactions.

## 6. What we built that upstream doesn't have

Numbered as port targets (reference numbers for future planning):

1. **Docker per-org isolation.** `~/.amux/orgs/<Org>.yml` → `amux-org-<name>` container with per-org mounts, SSH keys, read-only cred surfaces, `readonly_cross_mounts`. Upstream is tmux-only.
2. **Notes primitive.** `POST /api/notes/<name>` with `{"content":"..."}`. Pull-based docs. Confirmed absent upstream via `/api/notes` 404.
3. **Thread-as-Jeremy-inbox enforcement** → generalize to **Thread-as-USER-inbox** for multi-user. Upstream's `MessageTarget::Human` is already user-neutral; we would need per-user identity, inbox routing, per-user Pushover identity.
4. **Ember audit chain.** C3 + C4 + TIP-SHA/AUDITED-SHA guard (ER-523/525/529/536) + ER-547 provenance stamps + ER-591 verdict-first routing + ER-613 report-file fallback + ER-624 stale-todo re-boost + ER-626 SELECT-session fix. Zero equivalent upstream.
5. **Substrate doctrines wiki.** `wiki/Substrate-Doctrines.md`. Upstream has `docs/` + `AGENTS.md` + a monolithic `CLAUDE.md` but no survivable orchestration-system-of-record outside the code.
6. **Backup/restore contract with Cypra Notion sync.** `backup/amux-backup.sh` + `backup/restore-verify.sh` + mandatory board-ping-to-Cypra when the recovery contract changes.
7. **RESUME-HERE.md discipline.** Mandatory plan-of-record for every amux-server.py change. Survives restarts/compaction.
8. **Single-file deploy.** Grep-and-edit iteration speed. Fundamentally incompatible with a 4-crate workspace; the spirit (one place to look) is a Python-only property.
9. **iCal/S3 calendar feed.** `GET /api/calendar.ics` + auto-upload to `s3://ethan-personal/amux/calendar.ics` on every board write.
10. **ER-547 scheduled-delivery provenance stamp** (`posted_by_session` column).

## 7. Our scheduler surface (reference inventory)

### In-process `schedule_job(...)` registrations

| Interval | Job | What it does |
|---|---|---|
| 3s | `_yolo_loop` | Auto-accept confirmations |
| 15s | `_rate_limit_loop` | Token-bucket + Opus 429 recovery |
| 60s | `_snapshot_loop`, `_tmux_size_watchdog`, `_repos_scan`, `_board_watcher_gc` | tmux snapshots + size watchdog + repo discovery |
| 120s | `_reap_stale_browsers`, `_refresh_token_cache` | Chrome CDP + token cache |
| 300s | `_sweep_stale_todos`, `_sweep_stale_doing`, `_sweep_stale_todos_reboost`, `_evict_stale_caches`, `_threads_stale_working_reaper`, `_validate_api_key_job`, `_log_resource_snapshot`, `_email_sync_job` | Board watchdog + ER-624 + cache + api-key + email |
| 600s | `_kill_stale_ray`, `_enforce_archived_stopped` | Ray cleanup + archive enforcement |
| 1800s | `_cleanup_tmp` | tmp dir prune |
| 3600s | `_auto_archive_idle` | Idle session archive |
| 86400s | `_sweep_dormant_schedules`, `_cleanup_old_transcripts`, `_cleanup_logs`, `_cleanup_recordings`, `_db_maintenance` | Daily hygiene |

### User-defined `schedules` table

278 rows total; **11 currently enabled** (2026-10-01 snapshot):

- `0 */6 * * *` — AMUX system backup (SCHED-39), RTG-Research backup (SCHED-260)
- `7 3 * * *` — Nightly skills-sync (SCHED-219)
- `17 3 * * *` — Nightly api-hooks redeploy (SCHED-240)
- `30 4 * * *` — Daily context clear — AMUX-Watchdog (SCHED-43)
- `15 15 * * *` — Nightly disk cleanup, early Pushover if disk >88% (SCHED-49)
- `7 19 * * *` — Daily Crashlytics triage, all iOS verticals (SCHED-116)
- `0 21 * * *` — RTG Notion dashboard poll (SCHED-36)
- `0 7 * * 0` — Weekly Sunday: Lacrosse → FAMILY calendar mirror (SCHED-297)
- `0 14 * * 1` — Weekly skills-library curation (SCHED-42)
- `*/20 * * * *` — RTG-VS2017 build-box stall watchdog (SCHED-228)

### Fork-unique scheduler bits that would need special handling in any future port

- ER-547 `posted_by_session` provenance stamp — new column on upstream's schedule table.
- ER-624 `stale_todo_boost_count` + `stale_doing_nudged_at` sweep columns.
- `_fire_schedule_event` — event-triggered schedules (closed-loop orchestration).
- `_sweep_dormant_schedules` (AH-96) — alerts once-per-dormant for enabled=0 that never fired.

## 8. Upstream repo pulse — 2026-10-01

- **Latest commit: today, ~4 hrs before this snapshot** (`fix(cli): a --priority amux land pushes alone`).
- 385 commits in last 7 days. 2,167 in last 30 days.
- Aug 2026: 2,515 commits. Sep 2026: 2,188. Pre-sprint months (May/Jun): 77 / 179.
- **One primary author: Ethan Steininger — 2,115 of 2,167 last-30-day commits (97%).** Everyone else <20/mo.
- 13 unique authors in 90 days; 10 are drive-by (last contribution >30 days ago).
- `Claude Haiku` is a listed author — upstream also commits via Claude Code.
- Only semver-ish tag: `v0.9.108` (pre-1.0). All other tags are `ios-build-NNNN` internal CI.
- Single branch: `origin/main`. No stable branch, no release/* branches.
- Still fixing invariants (17 `fix(invariants)` commits in 14 days) — doctrine layer not frozen.
- Hot areas (last 14 days): projects, dashboard, peek, ci, board, cli, chat (AMUX-5432 "chat delegate" lands today), invariants.

## 9. The decision — stay-and-grow

Not migrating. Reasons in order:

1. **Our stated migration driver reverses on the pulse data.** "Don't fall behind" is not achievable against 70 commits/day. The only state is "merge forever." We'd spend effort tracking upstream, not building our thing.
2. **The real driver (team members on projects) doesn't require Rust.** Multi-user is additive to our Python stack — generalize threads from Jeremy-only to `Human`-equivalent, reuse `X-Amux-User-Email`, extend Pushover identity. ~1 week of work.
3. **Upstream is pre-1.0 with bus-factor-1 and no stable branch.** Porting our Docker-per-org / audit chain / notes / doctrines against HEAD means rebasing continuously against one architect's refactors. That's a job, not a migration.
4. **Our amux is stable, understood, under our control.** Trading that for an unfinished moving target to gain features we can backport instead makes no sense.

## 10. What we'll do instead (ordered)

1. **Multi-user in Python.** Generalize threads to `Human`-equivalent. Per-user identity via `X-Amux-User-Email` (already exists cloud-side). Per-user Pushover identity. Server-side inbox-rejection regex becomes per-user, not Jeremy-only.
2. **Selective backport of three upstream ideas:**
   - **Versioned memories with `expect_version` → 409.** Replaces LWW on memory writes.
   - **`/api/needs-input` triage endpoint.** One ordered pane of everything waiting on a user. Natural extension of multi-user.
   - **MCP `ready` probe** = credentials-on-disk-exist. Would have caught the 09-19 Google-connector regression.
3. **Skip the rest.** Collapsing threads/channels/board into one `Message` isn't worth the churn — our three-primitive split with social enforcement works and the fleet understands it.

## 11. Revisit triggers

Re-open the migration question when **any** of these fire:

- Upstream tags `v1.0.0` and publishes a stable branch.
- Ethan adds a second committer with sustained velocity (bus-factor >1).
- Upstream ships a notes-equivalent (would signal convergence toward our data model).
- Our Python monolith starts to hit real walls (currently ~65K lines, no wall in sight).
- Jeremy's team grows past the point where our board/channels/threads/notes four-primitive mental model is harder to teach than upstream's single-`Message` model.

## 12. Artifacts

- `/api/notes/rust-migration-research` — the live note version of this research (durable at `~/.amux/notes/rust-migration-research.md`).
- Eval server: `https://amux-eval.j3software.co:8824`. Owner token held by Jeremy; redacted here.
- Upstream clone used for this cycle: `git@github.com:mixpeek/amux` HEAD at `06e57db1` (2026-10-01).
- Prior cycle: [Upstream-Comparison-2026-08-19](Upstream-Comparison-2026-08-19.md).
