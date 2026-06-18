# Features added in this fork

Everything below is present in `jwesley-main` and **not** in upstream
`mixpeek/amux`. Grouped by area. Env vars referenced here live in
`~/.amux/server.env` (global) or `~/.amux/sessions/<name>.env` (per session).

## Notifications & push

- **Pushover push for all alerts.** Server-side alerts (session needs input,
  auto-restart, schedule events, `/api/notifications`) fan out to Pushover →
  iOS/Android. Config in `server.env`: `AMUX_PUSHOVER_TOKEN`,
  `AMUX_PUSHOVER_USER`. Settings UI has a "Pushover Notifications" section with
  Save + Send-test. Endpoint: `POST /api/notifications`, plus
  `POST /api/pushover/test`.
- **Needs-input push.** When a session transitions to `waiting`, a Pushover
  notification fires — **unless** that session has `CC_AUTO_CONTINUE=1` (then
  auto-continue handles it and the push is suppressed).
- **Per-schedule `notify` flag.** Schedules carry a `notify` column; silent
  recurring tasks (watchdog, backups, event-triggered routers) set `notify=0`
  so they don't spam the feed. Event-triggered schedules default to silent.

## Webhooks & inbound integrations

- **SMS Eagle inbound webhook** — receives inbound SMS; allowed without an auth
  token (it's an external poster).
- **SmarterTrack new-chat webhook** — endpoint that also handles GET validation
  requests SmarterTrack sends.

## Session UX

- **Session icon picker** — assign an emoji per session (`CC_ICON`), shown at
  card-name height. (Bug fixed: `closeIconPicker` had nulled the target before
  the PATCH — `5280f8d`.)
- **Session card color picker** — `CC_COLOR` env var, color-swatch UI, card
  border tint, and the color is applied to that session's **tmux status bar**
  so the terminal itself is visually identifiable.
- **Stop session** in the card menu.
- **Sticky-working hysteresis** — the grouped Sessions view holds a session in
  the "Working" group for ~60s after it was last seen active, so it stops
  whack-a-mole-ing between Working and Idle every time a spinner frame is
  missed. Display-only (`displayStatus()` client-side); the raw status the
  watchdog/auto-continue read is untouched. (`9d6ed85`)
- **Mobile send-button layout, Shift+Tab chip** in the input chip bar.

## Repositories tab

Scans `/mnt/gitdata/` for git repos and shows each repo's dirty/unpushed state
and last commit — a fleet-wide "what's uncommitted / unpushed" view.

## Board

- **`review` and `verified` statuses** added to the kanban (after `done`) and
  to the `amux board` CLI. The dual-audit flow uses them: worker → `review` →
  audited → `verified`.
- **Org partitioning** — board items carry an `org` column derived from the
  assigned session's `CC_ORG`. `GET /api/board?org=X` filters server-side
  (`org=none` = unpartitioned). This makes fleet boundaries **structural**: each
  org's Dispatch queries only its own items, so cross-org items are invisible,
  not merely forbidden. Org is set at create/first-assign/claim and does not
  follow later reassignment. See [Orchestration-Architecture](Orchestration-Architecture.md).
- **Board-first coordination doctrine** — inter-agent handoffs/results go on the
  board or notes (pull-based), not channel injection. A `/quiet` skill exists.

## Models

- **`claude-opus-4-8`** (and 1M-context variants) in all model selectors.
  History note: agents were briefly on `claude-fable-5`; when Fable was
  discontinued (2026-06-17) they were moved back to `claude-opus-4-8`.

## Backup

- **`amux-backup.sh`** — full system backup: `~/.amux/` (DB, sessions, notes,
  server.env, tls, auth_token), a SQLite dump, Claude conversation JSONLs, and
  system files (systemd units, start scripts). Generates a `README.md` restore
  guide. See [Operations](Operations.md).

## Commit guard (present, currently DISABLED)

A server feature (`AMUX_COMMIT_GUARD`, per-session override
`AMUX_COMMIT_GUARD_SESSION`) that nudges a session when it goes idle with
uncommitted changes. **Turned OFF globally on 2026-06-18** (`AMUX_COMMIT_GUARD=0`
in server.env) because the interjection disrupted agent workflow. The separate
**verify-gate** (blocks PATCHing an item to `verified` while its checkout is
dirty, with a `force` override) remains ON — it guards the board API and does
not interject into terminals.

## Agent templates & CLAUDE.md conventions

The project CLAUDE.md / agent templates carry added standing rules (these shape
every agent's behavior):
- **Scorpio-only vCenter rule** — only the `Scorpio` session may touch
  vCenter/VMware; others post a board task to Scorpio.
- **Board-first / channel-discipline** inter-agent coordination rules.
- **Find-before-proceeding** and **read-comments-above-functions** research rules.
- **Function-comment standards** and **universal agent rules** in the project
  templates.
- **Quality-Over-Speed** note (do not cut corners; lazy work triggers a full audit).
