# Research Project

## Research Question
[What are we trying to find out? Be specific — vague questions produce vague answers.]

## Why This Matters
[What decision or action does this research inform?]

## Scope & Constraints
- Time horizon: [e.g. "focus on last 3 years"]
- Geographic scope: [e.g. "US market only"]
- Out of scope: [what we're explicitly NOT researching]

## File Structure
```
research/
├── CLAUDE.md           ← You are here
├── sources/            # Raw source material — one file per source
│   └── TEMPLATE.md     # Copy this for each new source
├── notes/              # Running notes, hypotheses, open questions
│   ├── questions.md    # Questions to answer (checked off as answered)
│   └── findings.md     # Key findings as they emerge
├── drafts/             # Work-in-progress documents
└── output/             # Final deliverables (reports, memos, presentations)
```

## Research Process
1. **Define** — clarify the question, agree on scope (this file)
2. **Gather** — collect sources into `sources/`, one file each with URL + summary
3. **Synthesize** — update `notes/findings.md` as patterns emerge
4. **Draft** — produce structured draft in `drafts/`
5. **Finalize** — clean up into `output/` deliverable

## Source Standards
- Every claim needs a source — cite URL, date, and author where possible
- Rate source reliability: Primary (official data) / Secondary (analysis) / Opinion
- When sources conflict, flag it explicitly — don't pick a side silently
- Prefer recent sources unless historical context is the point

## Output Format
Final reports should include:
- **Executive summary** (3–5 bullets, fits on one screen)
- **Detailed findings** organized by theme, with citations
- **Open questions** — what we still don't know
- **Recommendations** — what to do based on the findings

## Asking Good Questions
When I say "research X", before diving in, confirm:
1. What format do I want the output in?
2. Is this for a specific decision? If so, what is it?
3. How deep — quick scan (1–2 hours) or thorough (deep dive)?

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
