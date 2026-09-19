# Substrate Doctrines

Cross-cutting principles the substrate should hold, captured from the incident
trail. These aren't features — they're the invariants that keep the substrate
from re-shipping the same bug in a new shape. Every doctrine here comes with
its citing incident so future agents can weigh it against fresh evidence
rather than treating it as unquestioned dogma.

Add to this file whenever a substrate fix rests on a general principle worth
naming. Cite the incident that surfaced it; the principle only earns its
place by being multi-incident. A doctrine without an incident chain is folk
wisdom.

---

## Route on ground truth, not on a derived symptom

**Framing (Ember-Research 2026-09-19, ER-591 close):** *"The substrate KNEW
the real state (verdicts disagree / tip moved / banner active) but surfaced a
DERIVED symptom instead of the ground truth. Verdict-first, tip-first,
state-first: route on what you KNOW, not on what a secondary check happens
to trip on first."*

**Incident chain (six of this week's twelve fixes):**

- **Verdict-first (ER-591, `f5ae8a21`).** C4's sha-hold pre-empted SPLIT and
  FAIL/FAIL outcomes. Sha-mismatch is a derived symptom; the ground truth
  is that verdicts disagree (adjudicate) or both fail (worker re-take).
  The sha-hold arrived at Research/worker as the wrong frame. Fix: gate
  sha-check on `both_accept`; SPLIT and FAIL/FAIL route to their natural
  outcome. Ember-Research: "the sha-freshness gate is about avoiding a
  FALSE VERIFIED, which only pass/pass can produce."
- **TIP-SHA as oracle (ER-523, `240244fe`).** Pairwise AUDITED-SHA compare
  passed when both auditors happened to record the SAME STALE sha. The
  ground truth is the target's current tip; audit-vs-audit is a derived
  proxy. Fix: TIP-SHA declaration on target became the oracle; both
  auditors' shas checked against it.
- **TIP-SHA change is a mint trigger (ER-556, `1e54def5`).** Status-transition
  as the mint trigger was a derived proxy for "target ready for audit."
  The ground truth is "target now points at a sha no existing pair covers."
  Fix: PATCH cascade fires mint on any review-state desc change; dedup
  keys on AUDITED-SHA vs TIP-SHA match, not on timestamp.
- **Symmetric freshness (ER-559, `fb1dd51d`).** The sha-freshness guard
  gated only the PASS side. Ground truth is that stale audits are stale
  regardless of verdict direction — an adjudicated stale FAIL bounces
  possibly-already-fixed work. Fix: the same helper gates single-audit
  and C3 adjudication paths.
- **POST-at-review mint (ER-536, `426df48a`).** Items POSTed directly at
  status=review skipped the mint hook. Ground truth is "item is at
  review and needs audits"; status-transition was a derived trigger.
  Fix: POST cascade fires the mint hook too.
- **State-first (Ember-Research ER-557 / rate-limit banner + queued
  schedules).** Substrate tracked `rate_limit_banner=True` and
  `rate_limited_until` but scheduler kept firing SCHED-* tmux deliveries
  into a banner-blocked pane for 26h. Ground truth is "session is
  banner-blocked; do not queue text into its pane." (Watchdog + scheduler
  backpressure held on Jeremy's word 2026-09-19 — will ship as
  additive.)

**How to apply to a new hook:** ask what event the outcome depends on and
route on THAT event, not on a secondary indicator that happens to correlate
with it most of the time. If the secondary indicator disagrees with the
event, the outcome should route on the event and log the disagreement as
observability, not pre-empt.

**Doctrine's own boundary:** ground-truth routing works when the substrate
actually knows the ground truth. Where the substrate can't derive it
(e.g. "is this branch tip the current one?" — the server has no git), the
solution is a declared marker (TIP-SHA convention) — declared shared state,
not silent derivation.

---

## A fix that lives only in mutable state is a fix on a timer

**Framing (Ember-Research 2026-09-19, ER-586 close):** *"The record-vs-reality
class: a fix that lives only in mutable state is a fix on a timer. Bake the
symlinks into the container/box bootstrap so the next reprovision cannot
silently undo them."*

**Incident chain:**

- **AH-32 pub-cache symlinks (2026-07, then reverted by a container
  reprovision 2026-09-19, discovered via ER-586).** The July fix moved
  `~/.pub-cache` etc. out of container writable layers via a symlink into
  a shared host mount. That fix was applied to running containers'
  filesystems only. When a container was recreated, the symlink went with
  the old writable layer; the new writable layer was a real directory
  again. Cypra + J3-Marketing hit an unrelated version of this class the
  same day (bind-mount source change requires container recreate; live
  filesystem tweaks would have been lost).
- **Doctrine's own inclusion:** every mount worth its comment gets a
  "why" line pointing at the incident that justified it — a mount
  without its why is one refactor from deletion, same shape one level
  up (Ember-Research 2026-09-19, ER-586 close ask 3).

**How to apply:** if you're editing a running container's filesystem to fix
something, ask whether the fix would survive `docker stop && docker rm &&
docker run`. If not, it belongs in the org spec YAML (bind-mount, env,
build step) OR in the base image OR in a startup script the container runs
on every launch. And whatever you put in the spec, put the incident that
justified it in the comment.

---

## Silence is the failure mode

**Framing (Ember-Research 2026-09-15, ER-523 close):** *"A false verified is
worse than no verdict, and a procedural control that loses a race is not a
control — race-prone controls need a server-side backstop."*

**Extended framing (Ember-Research 2026-09-16, ER-536):** *"The failure mode
is SILENCE, and silence is indistinguishable from audits-still-running.
Third mint-family gap found by going LOOKING instead of waiting — that
habit is the real control."*

**Incident chain:**

- **Mint-skip loudness (ER-536, `426df48a`).** `_mint_audit_pair_unguarded`
  had ~6 early-return paths, all silent. A skipped mint was
  indistinguishable from auditor neglect. Fix: `[mint-skip] <id>: <reason>`
  slog on every early return.
- **RA-1558 flip loop (2026-09-11, `ee63f9f4`).** Substrate tracked
  session-notify state but a chain of silent no-ops between the
  submit-verify retry and the notify-flag reset produced an 8-second
  flip loop that looked identical to a healthy running task from the
  outside.
- **Rate-limit banner block (2026-09-19 ER-547-adjacent).** 26h banner
  block on Ember-Research produced no Pushover to Jeremy. Substrate
  knew the state; nothing surfaced it.

**How to apply:** any early return in a hook that affects fleet behavior
gets a slog. Any state the substrate KNOWS but doesn't SURFACE to the
human is a bug waiting for someone to notice it after the damage. When
you add a new "skip this case" branch, add its `[<hook-name>-skip]` slog
in the same commit.

---

## Same principle at multiple layers

The three doctrines above are the same shape at different scales:

- **Route on ground truth** — hook-level: the outcome depends on what
  event actually happened, not a derived indicator.
- **Fix on a timer** — provision-level: the fix depends on what state
  actually persists, not what state you happen to see running now.
- **Silence is the failure mode** — observability-level: the operator
  can act only on what they actually see, not on what the substrate
  happens to track internally.

Applied together: the substrate should routes on what it knows, in a way
that survives reprovisioning, and surfaces what it knows about non-obvious
skips.

---

## When to add to this file

New doctrines earn their place by:

1. **Multi-incident.** One incident is a bug; two is a coincidence;
   three+ is a class worth naming.
2. **A framing quote worth preserving.** The doctrine's memorable in the
   words the incident's investigator used, not paraphrased into
   substrate-speak.
3. **A "how to apply" section.** The doctrine is only useful if a future
   agent reading it can turn it into a concrete decision.

Delete an entry only if it's actively wrong (superseded by a better
principle from a newer incident). A doctrine can be REFINED without being
deleted — add an "amendment" subsection with its own citation.
