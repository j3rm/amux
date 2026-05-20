# Software Project

## Project Overview
[What does this project do? Who uses it? Why does it exist?]

## Tech Stack
- Language(s): [e.g. TypeScript, Python]
- Framework(s): [e.g. Next.js, FastAPI]
- Database: [e.g. Postgres, SQLite]
- Key dependencies: [notable libraries]

## Key Commands
```bash
# Install dependencies
npm install          # or: pip install -r requirements.txt

# Development server
npm run dev          # or: python app.py

# Tests
npm test             # or: pytest

# Lint / format
npm run lint         # or: ruff check .

# Build
npm run build
```

## Architecture
[1–3 sentence high-level description. E.g. "Next.js frontend calls a FastAPI backend. All state lives in Postgres. Auth is handled by Clerk."]

## Working Conventions
- Read existing code before modifying anything — never guess at patterns
- Keep commits small and focused (one logical change per commit)
- Write or update tests for any new behavior
- Run the full test suite before marking a task done
- Leave code cleaner than you found it, but don't refactor beyond the task

## File Structure
```
[describe the key directories and what lives there]
```

## Open Issues / Backlog
[Link to GitHub issues, Linear, or list priorities inline]

## Gotchas
[Known footguns, env vars needed, non-obvious things Claude should know]

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
