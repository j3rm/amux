#!/usr/bin/env python3
"""Preventive session recycler — catches the CC_AUTO_CONTINUE compose-no-submit
failure (see notes/substrate-finding-2026-07-14-auto-continue-no-submit).

Failure signature: Claude Code composes a next-step prompt into its input
buffer but never submits it. Session sits idle with actionable intent stranded
in the pane. Recovery is a session-only tmux kill + wake; fresh session picks
up from board + memory.

Procedure (deterministic, no LLM):

  1. Peek every running session (top of pane).
  2. Detect the failure signature:
       (a) Text at the ready prompt (`❯ <words>`) not followed by a spinner
       (b) No in-progress marker in the last few lines (Actioning/Cogitated/
           Puzzling/Slithered/Brewed/Crunched/Sautéed/Working)
       (c) Not just a bare newline / hint text
  3. Persist per-session detection state to
       ~/.amux/recycle-state.json
     Same buffer text seen TWICE in a row across watchdog cycles = flap-proof;
     first sighting is recorded and returned as "flagged", second consecutive
     sighting triggers action.
  4. Before action, board-honesty check: for each item currently `doing` and
     assigned to this session, PATCH back to `todo` if the pane doesn't
     mention working it (agent visibly forgot to close the item).
  5. Recycle:
       - Container-mode session: `docker exec amux-org-<org> tmux kill-session
         -t amux-<name>`
       - Host-mode session: `tmux kill-session -t amux-<name>`
       Then POST /api/sessions/<name>/send with empty text to auto-wake.
  6. Print one line per session for schedule_runs.note capture (first 500
     chars kept by server).

HARD RULES (mirror watchdog.py):
  - Only recycle when buffer text has been the SAME across 2+ cycles.
  - Never touch a session showing an active spinner in the last few lines.
  - Never recycle during a still-running task (pane is a stream of new lines
    → detection resets naturally).
  - Never touch host-only critical sessions (`amux-helper`) — hardcoded skip
    list to prevent accidentally recycling the operator.
  - Dry-run by default. `--act` required to actually kill and wake.
"""

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request

AMUX_URL = os.environ.get("AMUX_URL", "https://localhost:8822")
STATE_PATH = os.path.expanduser("~/.amux/recycle-state.json")

# Sessions we never recycle even if they trip detection. amux-helper handles
# ops; recycling it mid-work would kill Jeremy's own operator session.
NEVER_RECYCLE = {"amux-helper"}

# In-progress markers Claude Code emits during active work. If ANY appears in
# the last ~500 chars of pane, skip detection — the session is working.
SPINNER_RE = re.compile(
    r"\b(Actioning|Cogitat(?:ing|ed)|Puzzling|Slither(?:ing|ed)|Brew(?:ing|ed)|"
    r"Crunch(?:ing|ed)|Saut(?:é|e)(?:ing|ed)|Work(?:ing|ed)|"
    r"Churned|Cook(?:ing|ed)|Ferment(?:ing|ed))\b",
    re.IGNORECASE,
)

# ANSI-stripping helpers
_ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_ESC = re.compile(r"\x1b[()][A-Z0-9]|\x1b[=>]")


def strip_ansi(s: str) -> str:
    s = _ANSI_CSI.sub("", s)
    s = _ANSI_OSC.sub("", s)
    s = _ANSI_ESC.sub("", s)
    return s


# Rating modal Claude Code shows after some completions. When present, it
# intercepts Enter keys — so a subsequent compose lands in the input buffer
# but never submits. This is the observed mechanism behind CC_AUTO_CONTINUE
# compose-no-submit (2026-07-15 finding).
RATING_MODAL_RE = re.compile(r"How is Claude doing this session\?")

# Buffer text patterns that are NOT real user compose — filter these out.
NOISE_BUFFERS = {
    "<no suggestion>",  # Claude Code placeholder when it has no autoreply
}

# Text-in-buffer at the ready prompt. Claude Code uses `❯ ` followed by the
# composed text, then a divider line of ─/━ characters. The character between
# `❯` and the text can be a regular space OR U+00A0 (non-breaking space) —
# both observed in the wild.
BUFFER_RE = re.compile(
    r"(?<!\S)❯[  ]+([^\n]{3,300}?)\s*\n[━─]{20,}",
)


_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _get(path: str):
    req = urllib.request.Request(AMUX_URL + path)
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def _post(path: str, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        AMUX_URL + path, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def _patch(path: str, body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        AMUX_URL + path, data=data, method="PATCH",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def _load_state() -> dict:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def _session_org(session_name: str) -> str | None:
    """Read CC_RUNTIME from the session's .env file. Returns the org name for
    docker:<org> runtimes, None for host-mode sessions."""
    env_path = os.path.expanduser(f"~/.amux/sessions/{session_name}.env")
    if not os.path.isfile(env_path):
        return None
    for line in open(env_path):
        line = line.strip()
        if line.startswith("CC_RUNTIME="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val.startswith("docker:"):
                return val.split(":", 1)[1]
            return None
    return None


def _detect(peek_text: str) -> str | None:
    """Return the buffer text if the compose-no-submit signature is present,
    otherwise None."""
    text = strip_ansi(peek_text)
    # Skip if the pane shows work-in-progress in the last chunk.
    if SPINNER_RE.search(text[-800:]):
        return None
    # Take the LAST buffer-shape match (there may be historical ones earlier
    # in the peek from prior submits — only the CURRENT ready prompt matters).
    matches = BUFFER_RE.findall(text)
    if not matches:
        return None
    buf = matches[-1].strip()
    # Skip placeholder hints Claude Code shows when there's no autoreply.
    if buf in NOISE_BUFFERS:
        return None
    # Claude Code placeholder suggestions: `Try"..."`, `Ask "..."`, etc.
    # Match with or without a space between the verb and the quote/text.
    if re.match(r"^(Try|Ask|How|What)\b", buf) and '"' in buf:
        return None
    # Skip slash-commands typed but never submitted (usually a Claude Code UX
    # artifact — `/exit`, `/resume`, `/tui default`, etc. — not stranded work).
    if buf.startswith("/"):
        return None
    return buf


def _board_honesty_reset(session_name: str, peek_text: str,
                        act: bool) -> list[str]:
    """PATCH `doing`-status items assigned to `session_name` back to `todo`
    if the pane text doesn't mention the item. Returns list of ids reset."""
    try:
        board = _get("/api/board")
    except Exception:
        return []
    reset = []
    pane = strip_ansi(peek_text)
    for item in board:
        if (item.get("session") or "").strip() != session_name:
            continue
        if item.get("status") != "doing":
            continue
        item_id = item["id"]
        if item_id in pane:
            continue  # visibly being worked (or at least mentioned recently)
        if act:
            try:
                _patch(
                    f"/api/board/{item_id}",
                    {
                        "status": "todo",
                        "desc_append": (
                            f"\n\n[{time.strftime('%Y-%m-%d %H:%M')} recycle.py]"
                            f" Reset doing → todo before session-only recycle of"
                            f" {session_name} (CC_AUTO_CONTINUE compose-no-submit"
                            f" failure; item wasn't visibly in progress in pane)."
                        ),
                    },
                )
                reset.append(item_id)
            except Exception:
                pass
        else:
            reset.append(item_id + "(dry)")
    return reset


def _recycle(session_name: str, org: str | None, act: bool) -> str:
    """Kill the session's tmux (session-only, container preserved for org
    containers) then POST /send to auto-wake. Returns a status word."""
    tmux_target = f"amux-{session_name}"
    if org:
        cmd = ["docker", "exec", f"amux-org-{org}", "tmux", "kill-session",
               "-t", tmux_target]
    else:
        cmd = ["tmux", "kill-session", "-t", tmux_target]
    if not act:
        return "dry-run"
    try:
        subprocess.run(cmd, capture_output=True, timeout=10, check=False)
    except Exception as e:
        return f"kill-failed:{e}"
    try:
        _post(f"/api/sessions/{session_name}/send", {"text": ""})
        return "recycled"
    except Exception as e:
        return f"wake-failed:{e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--act", action="store_true",
                    help="Actually kill+wake stuck sessions. Default: dry-run.")
    args = ap.parse_args()

    try:
        sessions = _get("/api/sessions")
    except Exception as e:
        print(f"recycle: failed to fetch sessions: {e}", file=sys.stderr)
        return 1

    state = _load_state()
    now = int(time.time())

    lines: list[str] = []
    n_flagged = 0
    n_recycled = 0
    n_cleared = 0

    for s in sessions:
        name = (s.get("name") or "").strip()
        if not name or name in NEVER_RECYCLE:
            continue
        if (s.get("status") or "").strip() not in {"idle", "waiting", "active"}:
            # Session isn't running — nothing to detect.
            if name in state:
                del state[name]
                n_cleared += 1
            continue
        try:
            peek = _get(f"/api/sessions/{name}/peek?lines=30").get("output", "")
        except Exception:
            continue

        buf = _detect(peek)
        prev = state.get(name)

        if buf is None:
            # No signature — clear any stale flag (agent unstuck on its own or
            # actively working).
            if prev:
                state.pop(name, None)
                n_cleared += 1
                lines.append(f"{name}: cleared (unstuck)")
            continue

        if prev and prev.get("buffer") == buf:
            # Same buffer text as the previous cycle → recycle candidate.
            org = _session_org(name)
            reset = _board_honesty_reset(name, peek, args.act)
            result = _recycle(name, org, args.act)
            n_recycled += 1
            reset_note = f" board-reset:{','.join(reset)}" if reset else ""
            lines.append(
                f"{name}: {result} buf={buf[:60]!r}{reset_note}"
            )
            if args.act:
                state.pop(name, None)
        else:
            # First sighting → flag and wait for next cycle to confirm.
            state[name] = {"buffer": buf, "first_seen": now}
            n_flagged += 1
            lines.append(f"{name}: flagged buf={buf[:60]!r}")

    _save_state(state)

    mode = "act" if args.act else "dry-run"
    summary = (
        f"Recycle[{mode}]: {n_flagged} flagged, {n_recycled} recycled, "
        f"{n_cleared} cleared. " + " | ".join(lines)
    )
    print(summary[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
