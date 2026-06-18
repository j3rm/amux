# Multi-agent orchestration architecture

**This is the most important page to preserve.** Most of this system lives
*outside* `amux-server.py`:
- agent **role files** in `/mnt/gitdata/<Org>/.agents/<session>/CLAUDE.md`
  (Claude agents) and `AGENTS.md` (Codex agents) — and the **org roots are not
  git repos**, so these files exist only on local disk + the amux backup.
- **schedule prompts** stored as rows in `~/.amux/amux.db` (the `schedules`
  table) — not in any file.

If local disk is lost, this page is the rebuild spec.

## The star topology (ruled by Jeremy, 2026-06-11)

All control flow runs through **Dispatch** via the board:

```
            Jeremy
              │
        Master Research        (plans/decides/adjudicates — no real work)
              │  (board)
           Dispatch            (routes only — no real work; the hub)
        ┌─────┼─────┐
     workers  …  workers       (the ONLY agents that edit code)
        │
     review → dual auditors    (Codex + Opus48, independent)
        │
     verified / escalate
```

- **Research** (e.g. `RTG-Research`, `Ember-Research`) — premium model
  (Opus 4.8; was Fable until discontinued). Plans, decomposes, adjudicates
  auditor disagreements. **Read-only**, never implements.
- **Dispatch** (`RTG-Dispatch`, `Ember-Dispatch`) — Haiku (cheapest). Routes
  work, creates audit pairs, applies verdicts. Never implements/researches.
- **Workers** (`RTG-ActAS`, `RTG-ACPSAS`, …) — default model (Sonnet). The only
  agents that touch code, each owning one repo.
- **Auditors** — two per org, different model families:
  `RTG-Audit-Codex` + `RTG-Audit-Opus48`, `Ember-Audit-Codex` +
  `Ember-Audit-Opus48`. Every `review` item is audited by **both,
  independently** — cross-provider disagreement is the signal (Codex repeatedly
  caught real bugs the Claude auditor passed, and vice versa).
- **EmberCoreMigration** — a sub-hub coordinator for the .NET Core migration;
  the only contact for the Core sub-agents (`Ember_Auth_API_Core`,
  `EmberCRM_API_Core`).
- **Standalone client agents** (`CD-*`, e.g. `CD-Wyoming`, `CD-WattcoAccMigration`)
  — NOT part of the star. Each owns one client folder under
  `/mnt/gitdata/ClientData/<client>/`, takes direction from Jeremy directly,
  does its own work. Their root `CLAUDE.md` enforces "stay in your session /
  root folder" and points at the shared Zoho skills.

## AMUX-Watchdog (liveness layer — distinct from Dispatch)

- Session `AMUX-Watchdog`, Haiku, `SCHED-38`. Event-triggered on
  `session_idle` + `board` (cooldown ~120s) with an hourly cron fallback.
- Job: peek every session that has a pending board item; if it's idle (by the
  **API `status` field**, not by scraping spinner words from scrollback — that
  was a false-positive bug), ring a doorbell (`/send` "you have pending board
  items"). It does **not** assign work — work is already routed; it only wakes.
- It is a separate axis from Dispatch: **Dispatch routes work; the watchdog
  restores liveness.** The watchdog must be able to poke Dispatch *directly*,
  because recovering a stalled Dispatch can't route *through* Dispatch.
- Stateless: `SCHED-43` sends a daily `/clear` so its context can't rot (a
  rotted watchdog rubber-stamped "✓" without running its checks).

## Dual-audit verdict resolution (acceptance-based, 2026-06-17)

When both auditors finish, resolve by **acceptance**, treating `PASS` and
`PASS-WITH-WARNINGS` both as ACCEPT and only `FAIL` as REJECT:
- **Both accept** (any mix of PASS / PASS-WITH-WARNINGS) → `verified`; if either
  noted warnings, file ONE non-blocking backlog follow-up. **No escalation.**
- **Both FAIL** → back to worker (`doing`) with merged findings.
- **Acceptance disagreement** (exactly one FAIL) → ONE escalation to Research,
  verbatim.
- A difference in *warnings* is never a disagreement — never escalate
  PASS vs PASS-WITH-WARNINGS (that burned the premium model on non-issues).
- **Settled-item guard**: never audit/escalate/verdict an item already
  `verified`/`done`/`discarded`. Only act on pairs whose target is in `review`.
  A *deliberate* re-audit = move the target back to `review` (allowed);
  *automatic* reprocessing of settled work = blocked.

## Org partitioning (structural fleet boundaries, 2026-06-12)

- `org` column on board items, derived from the assigned session's `CC_ORG`
  (explicit env var, no name heuristics) at create / first-assign / claim;
  it does **not** follow later reassignment.
- `GET /api/board?org=RTG` filters server-side (`org=none` = unpartitioned).
- Each Dispatch's schedule prompt queries only its own org → cross-org items are
  invisible, making the boundary structural, not just prompt-discipline.
- `CC_ORG` set per fleet: RTG, Ember, Cypra, LYNQ, Infra (Scorpio), amux.
  CD-* client agents are intentionally un-orged (standalone).

## Schedule prompts (the enforcement layer)

Recurring/triggered prompts in the `schedules` table. Key ones:
- `SCHED-38` — AMUX-Watchdog liveness procedure.
- `SCHED-40` / `SCHED-41` — RTG / Ember Dispatch loops (org-scoped query, hard
  exclusions, audit-freshness, adjudication application, dedup, settled-item
  guard, acceptance-based verdicts, routing-directive decomposition).
- `SCHED-42` — weekly Zoho skills-library curation (Cypra-PAA).
- `SCHED-43` — daily AMUX-Watchdog `/clear`.

## The hard-won principle: the per-wake PROMPT binds a Haiku agent

Repeatedly, a correct rule sat in a Dispatch **role file** while the **schedule
prompt** had drifted — and the agent followed the prompt. **Rules that must
bind a cheap model belong in the injected per-wake prompt** (and the role file),
not in ambient memory. Every major orchestration incident traced to this or to
an emergency rule lacking an idempotency/scope stop:
- Fabricated `done` on idle (auto-complete with no deliverable check).
- Auto-continue OFF removing all forward motion (over-correction).
- Blanket `RD-*` exclusion blocking actionable routing directives (prefix
  overload: process-directive vs actionable-routing).
- PASS-vs-PASS-WITH-WARNINGS over-escalation + reprocessing settled items.

The recurring fix shape: **narrow the trigger + add a "don't reprocess settled
state" guard**, and put it in the prompt.
