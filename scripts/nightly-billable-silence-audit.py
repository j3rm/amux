#!/usr/bin/env python3
"""Nightly billable-notes silence audit.

Fires ~08:30 each morning. Enumerates every active CD-* session and checks
the board for a `Nightly billable notes: <Client> — <yesterday-date>` item
posted to Cypra-PAA. If any expected CD-* agent DIDN'T post one, that's an
anomaly (crashed dispatcher, missed watchdog nudge, session down, agent
skipped the step) and the pipeline treats silence as broken, not zero-hour.

AH-10 requirement (2026-07-01): "a missing nightly note should be
indistinguishable from nothing to report only if you build detection for
it." This script is that detection.

On any missing CD-*, POSTs a single alert task to Cypra-PAA listing them.
Deterministic; zero LLM tokens.
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

AMUX_URL = os.environ.get("AMUX_URL", "https://localhost:8822")
CC_SESSIONS = Path.home() / ".amux" / "sessions"
BILLING_TARGET = "Cypra-PAA"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _get(path: str) -> object:
    req = urllib.request.Request(AMUX_URL + path)
    with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
        return json.loads(r.read())


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        AMUX_URL + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ctx, timeout=15) as r:
        return json.loads(r.read())


def _parse_env(env_file: Path) -> dict:
    cfg = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _cd_sessions() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(CC_SESSIONS.glob("CD-*.env")):
        name = f.stem
        cfg = _parse_env(f)
        if cfg.get("CC_ARCHIVED") == "1":
            continue
        out.append((name, cfg))
    return out


def _client_name(name: str, cfg: dict) -> str:
    return cfg.get("CC_DESC", "").split(" — ")[0].strip() or name.removeprefix("CD-")


def main() -> int:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    sessions = _cd_sessions()
    if not sessions:
        print("No CD-* sessions — nothing to audit.")
        return 0

    board = _get("/api/board")
    posted_by_session = set()
    posted_by_title = set()
    for i in board:
        if i.get("session") != BILLING_TARGET:
            continue
        title = i.get("title") or ""
        if not title.startswith("Nightly billable notes: "):
            continue
        if yesterday not in title:
            continue
        desc = i.get("desc") or ""
        for line in desc.splitlines():
            line = line.strip()
            if line.startswith("SOURCE_SESSION:"):
                posted_by_session.add(line.split(":", 1)[1].strip())
        posted_by_title.add(title)

    missing = []
    accounted = []
    for name, cfg in sessions:
        client = _client_name(name, cfg)
        expected_title = f"Nightly billable notes: {client} — {yesterday}"
        if name in posted_by_session or expected_title in posted_by_title:
            accounted.append(name)
        else:
            missing.append((name, client, expected_title))

    print(f"Nightly billable silence audit {yesterday}:")
    print(f"  accounted: {len(accounted)}  {' '.join(accounted)}")
    print(f"  missing:   {len(missing)}    {' '.join(m[0] for m in missing)}")

    if not missing:
        return 0

    lines = [
        f"Silence detected in the nightly billable pipeline for **{yesterday}**.",
        "",
        "The following CD-* agents did NOT post a nightly note to Cypra-PAA",
        "for yesterday's date. Silence is treated as a broken pipeline, not",
        "as a zero-hour day — verify each one:",
        "",
    ]
    for name, client, expected in missing:
        lines.append(f"- **{name}** ({client}) — expected title: `{expected}`")
    lines.extend([
        "",
        "Possible causes:",
        "- Session was down or looping when the nightly dispatcher fired",
        "- CD-* agent processed its trigger task but got stuck before posting",
        "- Watchdog didn't nudge (CD-* was in `doing` on some other work)",
        "- Manual override / agent chose not to post (should still post 0h)",
        "",
        f"Accounted-for CD-* sessions: {len(accounted)} of {len(accounted) + len(missing)}.",
        "",
        "This alert is posted by `nightly-billable-silence-audit.py`. Please",
        "reach out to each missing session (or ping Jeremy) so the day's",
        "billing pipeline can be reconciled before it drifts further.",
    ])
    body = {
        "title": f"Nightly billable silence audit — {yesterday}: {len(missing)} CD-* missing",
        "session": BILLING_TARGET,
        "status": "todo",
        "desc": "\n".join(lines),
        "org": "amux",
    }
    try:
        alert = _post("/api/board", body)
        print(f"Alert posted to Cypra: {alert.get('id')}")
    except Exception as e:
        print(f"Alert POST failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
