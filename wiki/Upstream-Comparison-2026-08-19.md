# Upstream comparison — 2026-08-19

Research notes from three questions Jeremy asked about `mixpeek/amux` upstream.
Kept as a wiki page (durable) so we can revisit when deciding what — if
anything — to selectively inherit.

**Snapshot at time of research:**
- Merge-base with upstream: `7d626af7` (2026-07-08)
- Upstream ahead: 2017 commits, ~1114 Python-era + ~900 Rust-migration
- Upstream deleted `amux-server.py` entirely on 2026-08-09 (Rust scaffold commit `4077c302`)
- Our fork: 121 fork-only commits, all Python single-file
- Decision recorded 2026-08-18: stay on our Python fork; cherry-pick ideas only

---

## 1. Why did upstream rewrite in Rust?

**Their doc**: `docs/rust-rebuild-plan.md` (9,199 lines). "Why Rust" section is
short and explicit:

1. **GIL / real concurrency.** Python's GIL serializes 30+ background jobs on
   ThreadingHTTPServer. Rust gives async + multi-threading without a global
   lock.
2. **Type-enforced invariants.** They wanted `Worker`, `Session`, `Backend`,
   `Message`, `Turn` etc. as structs with compile-time contracts, not dicts
   with sprawling conventions.
3. **Memory.** Python per-object overhead on a 24/7 desktop server alongside
   40+ workers.
4. **Single binary.** No venv, no lazy imports.

**Honest translation** (from mid-doc, not the marketing line): the Python
codebase had grown organically into an orchestrator without ever being
designed as one — 77k lines, single file, implicit orchestrator scattered
across pickup / advance-nudge / steering / snapshot / gates / session
startup. Rust was the excuse to redesign; the redesign is what they wanted.

**Nothing specific was Python-impossible.** They could have done the same
redesign in Python 3.12 with type stubs + `nogil` — they chose Rust for the
type discipline + single-binary deploy. Their own doc: *"Not a port — a
redesign that makes the implicit architecture explicit."*

**Reality check on the four reasons for OUR workload:**
- GIL — real but not painful; our 40+ workers work fine on ThreadingHTTPServer.
- Types — biggest reason for them, and honestly the one worth taking seriously.
- Memory — plausible; my fork sits ~350MB RSS after a week. Not painful.
- Single binary — ops convenience, not a capability gap.

---

## 2. Did they build anything like our Threads?

**Direct answer: no.** They built a unified `Message` entity, which is
adjacent but solves a different problem.

**Their model** (`crates/amux-core/src/message.rs`, Invariant 29):

```rust
enum MessageTarget {
    Worker(WorkerId),
    Group(GroupId),
    Human,   // "surfaced in the dashboard/notification lanes"
}

enum DeliveryState {
    Queued,
    Delivered { at },
    Acknowledged { at },
    ActedOn { at, task },
}
```

Everything — steering, `@worker` mentions, task chat, human-notify — is the
same `Message` type. Delivery is turn-boundary + forward-only state machine.

**Comparison to our Threads:**

|  | Upstream Message | Our Threads |
|---|---|---|
| Purpose | Universal message primitive | Jeremy-only personal inbox |
| Recipient variants | Worker / Group / Human (singular) | Jeremy only (empty `to_session`) |
| Cross-org isolation | No | Server-enforced 403 |
| Agent-to-agent | Same entity, different target | Separate: `Channels` (1:1) |
| Out-of-band notify | None documented (in-app only) | Pushover |
| CLI | None | `amux threads list/reply/flag/read/new` |
| "Thread" meaning | Parent-msg linkage column | UX concept (inbox conversations) |

**Where THEIR design is better:**
- **Turn-boundary delivery.** Steering messages queue and land at the
  recipient's next turn boundary — never interrupts mid-work. Our `/send`
  injects immediately, which can corrupt an in-progress prompt (we papered
  over it with `.busy` locks on remote agents).
- **Delivery state machine with audit trail.** "2026-07-27: a delivered
  message was reported swallowed; the delivery record is what settled it,
  so it must not be editable backwards" — a lesson we haven't formalized.
- **Group fan-out with per-recipient tracking.** They have Groups as
  first-class; we don't.

**Where OUR design is better:**
- Cross-org isolation (their `Human` is singular — leaks in multi-client).
- Pushover for out-of-band. Their notify path is in-app only.
- Actual inbox UX language, `amux threads` CLI, flag/star/paginate.
- Agent-to-agent noise separation via Channels — theirs conflates.

---

## 3. Docker / org / security

**Direct answer: their org support is DATA-level (query scoping); ours is
PROCESS-level (docker containers). Very different threat models.**

**Upstream's model:**
- ONE Dockerfile (`cloud/docker/Dockerfile`) — single-image Rust build.
  Everything runs in one Rust process.
- `crates/amux-server/src/api/org.rs`: lazy-created singleton "default" org,
  members + invites (24 random bytes, base64url, 7-day expiry).
- Multi-tenancy = `OrgId` threaded through every ID / query / index / SSE
  stream. Query-scoped isolation.
- **Invariant 52 — Capability policy.** Typed rules loaded at startup:
  ```rust
  enum DeploymentProfile { Personal, Cloud, Concierge }
  enum ActionClass {
      GitPush { branch_pattern },
      SendEmail,
      ExternalApiWrite { service },
      DeleteData { scope },
      CreateWorker,
  }
  ```
- **Invariant 48 — FleetCircuitBreaker.** Token spend + progress metrics
  with automatic pause points.

**Comparison:**

| | Upstream (Rust) | Our fork |
|---|---|---|
| Isolation layer | Data / query scoping | **Process / filesystem** (docker) |
| Container-per-org | No | Yes (`amux-org-<name>`) |
| Per-session home | No | Yes (`/homes/<session>/`) |
| Filesystem mounts | N/A | Per-org rw + cross-org ro (springboard) |
| Skill delivery filter | N/A | `skills-deny.txt` per org |
| Per-org secrets | Query-scoped | Bind-mounted SSH + gitconfig |
| Onboarding | Invite tokens + members API | Nothing — hand-edit env files |
| Capability policy | Typed rules per action | Ad-hoc env flags (`CC_REMOTE=1`, `CC_ARCHIVED=1`) |
| Rate limiting | FleetCircuitBreaker | Nothing formal |

**Where OURS is materially stronger:**
- Real OS-level isolation. Compromised session in `CD-SurfPrep` physically
  cannot read `RTG`'s filesystem. Their model is one WHERE-clause bug away
  from a cross-org leak.
- Zoho-denied orgs (EmberCRM, iSchedule, ShareScore, Scorpio) don't even
  have the skill files present — file-level, not runtime-filter.
- `CC_REMOTE=1` refusal — refuses impostor sessions before they exist.

**Where THEIRS is materially stronger:**
- Formal capability policy — one place to declare what each agent can do,
  vs our growing collection of env-flag guards.
- `OrgId` threaded uniformly — kills the "oh this endpoint doesn't filter by
  org" class of bugs. We keep discovering these (AH-58, AH-69, etc.).
- Invite flow — we can't onboard a new operator without hand-editing env
  files.
- FleetCircuitBreaker — token budgets with automatic pause. We have
  Pushover alerts.

---

## Worth inheriting later (Jeremy's shortlist to revisit)

Not doing today. Recording so we can pick these up when it makes sense:

### High value, moderate effort
1. **Turn-boundary message delivery.** Instead of `/send` injecting
   immediately, queue the text and deliver at the recipient's next
   turn-boundary. Fixes the "text lands mid-prompt and corrupts" edge case
   we've been managing with `.busy` locks. Would compose cleanly on top of
   existing session-status detection.

2. **`OrgId` on every board / thread / skill / session query as
   middleware, not per-endpoint.** Kills the whole class of "endpoint
   doesn't filter by org" bugs we keep discovering. Would require a query
   decorator pattern in the Python handlers.

3. **Formal `CapabilityPolicy` config file.** Consolidate our growing set
   of env-flag guards (`CC_REMOTE`, `CC_ARCHIVED`, `CC_MERGED_INTO` if we
   build it, etc.) into one YAML per org declaring "this agent may do
   these actions with these constraints." Easier to audit than 15
   scattered guards.

### Medium value, medium effort
4. **`DeliveryState` audit trail on board/message writes.** Forward-only
   state machine (`Queued → Delivered → Acknowledged → ActedOn`) with
   timestamps. Right now our board history is `updated` and prose in
   `desc`; adding a structured delivery ledger would help with "who saw
   this when" questions.

5. **Invite/member flow.** Token-based invites so we can eventually let a
   client or contractor touch a scoped view of amux without Jeremy
   hand-editing env files. Their shape (24-byte tokens, 7-day expiry,
   scope-bound) is clean and copyable.

### Low value / defer indefinitely
6. **FleetCircuitBreaker for token budgets.** We already have Pushover for
   over-spend alerts. Automatic pause is nicer but rarely-triggered.
7. **Groups as first-class.** Our multi-agent orgs already do this
   implicitly via session naming (`RTG-*`, `Ember-*`); a formal `GroupId`
   is nice-to-have.
8. **Fleet-wide SSE bus for cross-org events.** Nothing broken; skip.

---

## NOT worth inheriting

- **The Rust rewrite itself.** Their architecture redesign is defensible;
  the language change is aesthetic for our scale. We'd trade a "grep and
  edit one file" workflow for a Rust-toolchain dependency for zero user-
  facing benefit.
- **Query-scoped isolation as our primary model.** Our docker-per-org
  isolation is stronger against agent misbehavior; adding query scoping
  on top is worth doing (item #2 above) but replacing docker with it would
  be a downgrade.
- **Their unified Message model over our Threads/Channels/Board split.**
  Our split is deliberate — Jeremy needs an inbox that agent-to-agent
  chatter doesn't drown out. Their unified model conflates the two.

---

## Follow-ups when we revisit

- Re-fetch upstream: `git fetch origin` (they push several commits/day)
- Their design doc URL: `docs/rust-rebuild-plan.md` on `origin/main`
- Their message model: `crates/amux-core/src/message.rs`
- Their org API: `crates/amux-server/src/api/org.rs`
- Their capability plan: Invariant 52 in the rebuild-plan doc

Written by amux-helper on Jeremy's request, 2026-08-19 22:16.
