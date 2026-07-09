# Where Claude Code conversation JSONLs live — canonical reference

> Written 2026-07-09 after an incident where RTG-Research's history looked
> "missing" for an hour because it was stored under one encoding of its
> work-dir but Claude Code v2.1.205 was looking under a slightly different
> encoding. Ten Jeremy-personal sessions were affected. Documenting so
> no one has to re-derive this again.

## The short version

Every Claude Code conversation is a `<uuid>.jsonl` file at:

```
$HOME/.claude/projects/<encoded-work-dir>/<uuid>.jsonl
```

- `$HOME` is the runtime's HOME:
  - **host-mode session** → `/home/jwesley/.claude/projects/...` on the box
  - **docker-runtime session** → `/home/amux/.claude/projects/...` INSIDE the container, which is bind-mounted from `~/.amux/orgs/<org>/home/.claude/projects/...` on host
- `<encoded-work-dir>` is the session's `CC_DIR` after Claude Code's path-encoding rules (see below).
- `<uuid>.jsonl` — one per conversation. Optional sibling `<uuid>/` directory holds per-conversation subagent runs / tool-result blobs.

`/resume` lists conversations by scanning that exact dir for `*.jsonl` and grouping by `<encoded-work-dir>`. If the JSONL is in a differently-encoded sibling dir, `/resume` will not see it — even if the file is right there on the same filesystem.

## The path-encoding rule (v2.1.205, observed empirically)

Claude Code encodes an absolute work-dir into a project-dir name by replacing every `/` with `-` **and dropping every `.` in a path segment**. It does NOT literally keep dots.

Concretely, for `/mnt/gitdata/RemoteTechGroup/.agents/RTG-Research`:

- replace `/` with `-` → `-mnt-gitdata-RemoteTechGroup-.agents-RTG-Research`
- drop `.` from `.agents` → **`-mnt-gitdata-RemoteTechGroup--agents-RTG-Research`** ← the dir Claude Code actually reads/writes

The double dash between `RemoteTechGroup` and `agents` is where the leading `.` used to be. This is the CORRECT encoding.

You will also see `-mnt-gitdata-RemoteTechGroup-.agents-RTG-Research` dirs (dot preserved, single dash) sitting on disk with only a `memory/` subdir inside. Those are **amux memory-file placeholders**, not Claude Code project dirs. Claude Code does not look in them. Do not put JSONLs there — they will be invisible to `/resume`.

If you see BOTH encodings for the same session and JSONLs are in the `-.` one, they need to move to the `--` one.

## Which paths live in which container home — cheat sheet

For a docker-runtime session, always compute the target path this way:

```
host: /home/jwesley/.amux/orgs/<org>/home/.claude/projects/<encoded-work-dir>/*.jsonl
container-inside view: /home/amux/.claude/projects/<encoded-work-dir>/*.jsonl
```

They're the same bytes (bind mount). Edit either side; both see the change.

For a host-mode session:

```
/home/jwesley/.claude/projects/<encoded-work-dir>/*.jsonl
```

## Migrating history when moving a session from host to container

Whenever you flip a session's `CC_RUNTIME` from `host` to `docker:<org>`, its
conversation history stays on the host under `/home/jwesley/.claude/projects/`
and is invisible to the container. You have to copy it over.

**Copy pattern (always via rsync -a, preserve subagents/tool-results):**

```bash
rsync -a /home/jwesley/.claude/projects/<encoded-work-dir>/ \
         /home/jwesley/.amux/orgs/<org>/home/.claude/projects/<encoded-work-dir>/
```

Same encoded name on both sides. The trailing slashes matter (rsync semantics).

If the source is stored under the `-.` amux-memory-placeholder form instead
of the `--` real form, first move it: `mv */-.<seg>-*/ */--<seg>-*/`.

## Detect encoding-drift orphans

Run this to survey every container home for JSONLs that are stranded under the wrong encoding — where a `--<seg>-` dir has JSONLs but the sibling `-.<seg>-` dir is empty (or vice versa):

```bash
python3 - <<'PY'
from pathlib import Path
import re
def audit(name, base):
    p = Path(base)
    if not p.exists(): return
    for d in p.iterdir():
        if not d.is_dir(): continue
        m = re.search(r'--([A-Za-z][A-Za-z0-9_-]*)', d.name)
        if not m: continue
        sibling_name = d.name.replace(f'--{m.group(1)}', f'-.{m.group(1)}')
        sibling = p / sibling_name
        n_here = len(list(d.glob('*.jsonl')))
        n_sib = len(list(sibling.glob('*.jsonl'))) if sibling.exists() else 0
        if n_here > 0 and sibling.exists() and n_sib == 0:
            # d has real files; sibling is empty amux placeholder — fine
            pass
        elif n_here == 0 and sibling.exists() and n_sib > 0:
            print(f'{name}: JSONLs in wrong dir {sibling_name} ({n_sib}); '
                  f'move to correct {d.name}')
for org in ['RTG','EmberCRM','iSchedule','ShareScore','Cypra','Scorpio','Personal']:
    audit(org, f'/home/jwesley/.amux/orgs/{org}/home/.claude/projects')
audit('HOST', '/home/jwesley/.claude/projects')
PY
```

Run this every time you:
- Add a new session that touches a work-dir with a `.hidden` segment
- Upgrade Claude Code (the encoding could change again)
- Import history from a backup
- After any `mv` / `cp` between project dirs by hand

## Log of encoding-drift incidents

- **2026-07-09** — Ten Jeremy-personal sessions had their real (up-to-yesterday) history at `/home/jwesley/.claude/projects/-mnt-gitdata-*-\-agents-*/` (double-dash) but the container homes had only `/home/jwesley/.amux/orgs/*/home/.claude/projects/-mnt-gitdata-*-.agents-*/` (dot-preserved amux placeholders, empty). RTG-Research, RTG-Dispatch, RTG-Audit-Opus48, Ember-Audit-Opus48, EmberCoreMigration, Ember-Research, Ember-Dispatch, iSchedule-Research, iSchedule-Reviewer, iSchedule-Audit-Opus48. Fixed by `rsync -a` from HOST `--<seg>-` → container-home `--<seg>-`. Also RTG-Research got misdirected to `-.<seg>-` on the first attempt and had to be `mv`'d.

## Related

- [[amux-isolation-ops]] — the container auth + home layout that makes these paths what they are.
- [[reference-container-credential-ownership]] — which account owns each container.
