# Changelog — divergence from upstream `main`, and why

Every commit on `jwesley-main` not in upstream `mixpeek/amux@main`, grouped by
theme with the rationale. Regenerate the raw list with:

```bash
git fetch origin main
git log --reverse --pretty='%h %ad %s' --date=short origin/main..jwesley-main
```

Merge-base as of 2026-06-18: `45c82bd`. We periodically merge upstream in
(merge commits below) while keeping these features.

## Notifications / integrations (the original reason for the fork)
- `3d7dc5f` Pushover push for all amux alerts — get notified on phone when a
  session needs input or an alert fires.
- `a8c5a95` Pushover on `POST /api/notifications`.
- `44b30e8` push when a session goes to `waiting` (needs input).
- `066f80e` / `0d875ee` skip/limit that push when `CC_AUTO_CONTINUE` will handle
  it — avoid notifying for sessions that self-continue.
- `0874b00` + `2d1a6b6` SMS Eagle inbound webhook (no auth — external poster).
- `13eba1c` + `ce41e52` SmarterTrack new-chat webhook (+ GET validation).
- `507e75d` per-schedule `notify` flag — silence recurring tasks so they don't
  spam Pushover.
- `57e27e9` / `f9d3771` honor `AMUX_URL` from server.env; Shift+Tab chip.

## Board watcher → orchestration substrate
- `5d725d7` board watcher: nudge idle sessions with pending todo items — the
  seed of what became the AMUX-Watchdog.
- `0ed2a06` → `8b67381` walk-back of auto-closing board issues (early version of
  the later "never fabricate done" rule).
- `f076afe` `review` + `verified` board statuses in the CLI (dual-audit flow).
- `cfe8a30` **org partitioning** — structural fleet boundaries (see
  [Orchestration-Architecture](Orchestration-Architecture.md)).
- `e36635f` schedule POST honors `notify`; event-triggered default silent —
  the per-wake routers were flooding the feed.
- `6b329b0` **stop fabricating board completions on idle** — `_complete_session_board_issue`
  was marking ALL of a session's open items `done` on every idle transition with
  no deliverable check, fleet-wide. Made a no-op; status is PATCH-only now.

## Reliability: watchdog kill-loops & session lifecycle
- `f68fc0f`, `387b2dc`, `3718a5d`, `43b54bb`, `119ccdc`, `51d877c`, `063fb97`
  — a long campaign hardening the session watchdog against false-fires from
  stale tmux scrollback, resume-picker loops, spinner false-positives, and
  is_running mis-detection. Scope triggers to recent scrollback; check shell
  prompt before spinner scan; clear scrollback on start.
- `2f44350` / `ef7ce2e` guard the stale-process reaper from sessions active
  within the last 1–2h (don't reap live work).
- `a5f35c7` cherry-pick upstream hibernate-restart death-loop fix.
- `c0835aa` / `1d3a935` honor auto-compact toggle everywhere; don't compact on
  startup; persist cooldown across restarts.
- `9116b7e` **prevent conversation loss** on stale-reaper recycle and name
  ambiguity — agents were losing their conversation on recycle.
- `18f29f2` resume sessions by **UUID** to avoid the interactive picker loop.
- `fe9b89a` log duplicate JSONL sessions (picker diagnosis).
- `45916de` Codex launch uses `--dangerously-bypass-approvals-and-sandbox`
  (the valid flag) instead of an invalid `--full-auto`.

## Duplicate-server / scheduler integrity
- `f435e80` **disable `SO_REUSEPORT`** — two systemd supervisors had both bound
  :8822 silently, each running its own scheduler → schedules double-fired,
  `/send` arrived twice, dashboard requests split between divergent processes.
  Now a second instance fails to bind instead of silently double-running. (See
  [Operations](Operations.md) for the supervision history this caused.)

## Session UX
- `1510184` / `5280f8d` session icon picker (+ null-session save fix).
- `4c46f80` / `84ccdd0` session card color picker → also tints the tmux status bar.
- `91aaecc` Stop session in card menu.
- `f66e684` Repositories tab (scan /mnt/gitdata for dirty/unpushed repos).
- `9d6ed85` **sticky-working hysteresis** — stop the Working/Idle group
  whack-a-mole (display-only; raw status untouched).
- `c382f25` **peek scroll-lock freeze fix** — the scroll-lock could latch and
  never clear on mobile, freezing the conversation until an app reboot. Release
  on resume; guard programmatic scrolls; flush on unlock; relax bottom threshold.
- `e60f468` / `96cce27` mobile send-button wrap (added then reverted).

## Models
- `eb4b5f8` `claude-opus-4-8` in all model selectors.

## Backup & docs
- `f205b8d` / `efe506c` `amux-backup.sh` full-system backup + restore README.
- `f4648b9` gitignore backup files / MCP logs / macOS metadata.
- `361b5aa` Quality-Over-Speed note in CLAUDE.md.

## Agent templates / standing rules (shape every agent)
- `89448b2` Scorpio-only vCenter rule.
- `89928de` board-first inter-agent coordination + `/quiet` skill.
- `57a0ddf` find-before-proceeding + read-comments rules.
- `9c6f7c6` / `0ed579d` function-comment standards + universal agent rules.

## Upstream merges (kept our features each time)
`bd0a671`, `bd8b86c`, `829e696`, `f0a7fb3`, `48e01aa`, `ada42a1`, `d1ccdf6`,
`93bf149`, `06b10a9`, `be829ca`, `786ba4a` — periodic
`git fetch origin main` + merge. `90e1ba9` fixed broken JS from one such merge
(a missing brace/catch in `saveCommitGuard`). `9de19d5`/`3e8016d` a shared-SSE
perf experiment that was reverted.
