# amux (jwesley fork) — Wiki

This wiki documents the **`jwesley-main`** fork of amux: every feature added on
top of upstream `mixpeek/amux`, why each divergence exists, the multi-agent
orchestration system built around it, and how to operate it.

It is intentionally committed **into the repo** so it survives conversation
resets, agent context loss, and local-disk loss — it travels with the git
remote (`fork` → `j3rm/amux`). If you are an agent or a human picking this up
cold, start here.

## What this fork is

amux is a single-file dashboard + session manager for running many Claude
Code / Codex agents in tmux (`amux-server.py` — Python server + inline
HTML/CSS/JS). This fork keeps that single-file design and adds:

- **Push + integration layer** — Pushover alerts, inbound webhooks (SMS Eagle,
  SmarterTrack).
- **A multi-agent orchestration system** — a hub-and-spoke "star" of Dispatch /
  Research / worker / dual-auditor agents, a liveness watchdog, board org
  partitioning, and event-triggered schedules. Most of this lives *outside*
  `amux-server.py` (in agent role files and schedule prompts) — see
  [Orchestration-Architecture](Orchestration-Architecture.md). **That page is
  the only durable record of it.**
- **Session UX** — icons, colors, stop-from-menu, a Repositories tab,
  sticky-working grouping.
- **Reliability fixes** — watchdog kill-loop hardening, duplicate-server
  prevention, conversation-loss prevention, peek-refresh fixes.

## Pages

| Page | What's in it |
|---|---|
| [Features](Features.md) | Catalog of everything this fork adds, by area, with env vars/endpoints. |
| [Orchestration-Architecture](Orchestration-Architecture.md) | The agent star, watchdog, dual-audit, org partitioning, schedule prompts. Lives outside the code — capture it here. |
| [Changelog-vs-Main](Changelog-vs-Main.md) | Commit-grouped divergence from upstream `main`, each with the *why*. |
| [Operations](Operations.md) | Supervision (systemd), deploy, hot-reload, backup, the Zoho skills library, incident history. |
| [Remote-Agent-Doorbell](Remote-Agent-Doorbell.md) | Zero-token doorbell for remote agents (Windows/Mac) that live outside amux tmux — background board poller + terminal injector. Contributed by RTG-VS2017. |
| [Server-Hooks-And-Scripts](Server-Hooks-And-Scripts.md) | Substrate features added 2026-06-24: C3/C4 cascade hooks, escalation gate, RD routing hook, watchdog script, silently-dead detector, context-exhaustion auto-restart. Retires AMUX-Watchdog, RTG-Dispatch, Ember-Dispatch agents. |

## Relationship to upstream

- Upstream: `origin` → `git@github.com:mixpeek/amux.git` (we have **read-only**;
  pushes are denied).
- Our fork: `fork` → `git@github.com:j3rm/amux.git`, branch `jwesley-main`.
- We periodically `git fetch origin main` and merge upstream in, keeping our
  added features. Merge-base as of 2026-06-18: `45c82bd`.
- **"Deploy" here = commit + `git push fork jwesley-main`.** The running server
  hot-reloads on file save (mtime watcher), so a save is already a live deploy;
  the push is the durable backup. See [Operations](Operations.md).

## Single-codebase rule (inherited, still in force)

`amux-server.py` is identical for local (OSS) and cloud deployments — no
`if IS_CLOUD` branches. Environment differences are driven by headers/env vars,
not build flags. Always `python3 -c "import ast; ast.parse(open('amux-server.py').read())"`
after edits.
