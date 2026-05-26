# Project: [Name]

## What Is This
[1–2 sentence description. E.g. "Purchasing 15 acres of raw land in rural Vermont for a homestead build. Evaluating parcels, financing, zoning, and access."]

## Current Status
- Phase: [e.g. Due Diligence / Active Negotiation / Closed / Planning / Build]
- Last updated: [date]
- Next milestone: [what needs to happen next]
- Hard deadlines: [any dates that cannot move]

## File Structure
```
project/
├── CLAUDE.md           ← You are here
├── docs/               # Contracts, permits, official documents, emails
├── research/           # Vendor comparisons, market data, specs, quotes
├── contacts/           # People involved — vendors, agents, lawyers, etc.
├── decisions/          # Key decisions with rationale (log, never delete)
└── timeline/           # Milestones, deadlines, schedule
```

## Open Action Items
- [ ] [Task] — owner: [me/vendor/lawyer] — due: [date]
- [ ] ...

## Key Contacts
| Name | Role | Phone / Email | Notes |
|------|------|---------------|-------|
| [Name] | [e.g. Buyer's agent] | [contact] | [notes] |

## Budget
- Total budget: $[X]
- Committed so far: $[Y]
- Remaining: $[Z]
- Track all costs in `docs/budget.md`

## Decision Log
Key decisions are logged in `decisions/` with date, options considered, and rationale. Never delete or overwrite — always append.

## Working Rules
- When I give you new information, ask where it should be filed
- Flag anything time-sensitive or that could cause us to miss a deadline
- If I say "what's the status?", give me: current phase, open items, blockers, next milestone
- When researching vendors or options, always produce a comparison table before making a recommendation
- Keep `contacts/` up to date — I reference it constantly

## Keep function comments current with every change

When you modify a function — its logic, signature, side effects, or behavior —
update its comment block in the same edit. Do not leave comments that describe
what the function used to do. If a precondition changes, update it. If a new
caller is added, add it to the callers list. If a side effect is removed,
remove it from the comment. A stale comment is worse than no comment because
it actively misleads the next reader.

If you add a new call site to an existing function, go update that function's
comment to list you as a caller.

## Every new function gets a full comment block

Any function you write must have a comment block above it covering: why it
exists (not a restatement of its name), its callers, preconditions (what can
never be null and why, what state must exist), postconditions (what the caller
can rely on after it returns), any invariants that look wrong but are
intentional, side effects, return value semantics if surprising, lifecycle or
ordering constraints, concurrency safety, and any assumed logic that would only
fail if something upstream is already seriously broken.

Do not write comments that restate the function name or parameter names. Only
write what a reader could not infer from the code alone in under 5 seconds.

## When I say something exists, find it before proceeding

When I tell you that something exists in the codebase — a pattern, a service,
an integration, a convention — do not assume you understand it or take a
shortcut. Read the code, find the exact implementation, and confirm with me
what you found before making any changes based on it. If you cannot locate it
after a thorough search, ask me for more context. Never proceed on an
assumption when I have told you the answer is already in the codebase.

## Read comments above every function you examine

When researching how the codebase works, read the comments above every
function you look at — not just the function body. Comments explain how a
function is used by other parts of the system, constraints that are not
visible from the code alone, and context that would otherwise require tracing
every caller. A function body shows what it does; the comments above it show
why it exists and what depends on it. Missing the comments means missing the
context.

## vCenter / VMware infrastructure — Scorpio only

**Unless `$AMUX_SESSION` is `Scorpio`, you must NOT:**
- Run `govc` or any VMware vSphere CLI commands
- Connect to vCenter, ESXi hosts, or any VMware API endpoint
- Deploy, clone, snapshot, power on/off, or reconfigure virtual machines
- Read or modify vCenter inventory, datastores, networks, or resource pools

If a task requires VM deployment or vCenter interaction, post a board task to
Scorpio instead and do not proceed yourself:

```bash
curl -sk -X POST -H 'Content-Type: application/json' \
  -d '{"title":"<describe the VM task>","session":"Scorpio","status":"todo"}' \
  $AMUX_URL/api/board
```

Scorpio is the sole authorized agent for infrastructure provisioning.
Bypassing this risks conflicting deployments and untracked VM state.
