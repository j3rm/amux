"""
writeup_handoff_auto_mint — auto-mint the Cypra-PAA handoff (step 4) when a
Nightly billable-notes writeup source item PATCHes to review.

Motivation (Cypra CP-75 silence audit, 2026-07-04): the nightly-writeup
template makes agents responsible for step 4 (posting a CP-* to Cypra-PAA
with the packaged content). Agents that treat "PATCH to review" as terminal
skip step 4. The failure is silent — writeup looks done from the source
board, PAA silence audit is the only thing that surfaces it 8h later.

Fix: remove step 4 from agent responsibility. The moment a writeup item
transitions to review, this workflow mints the CP-* handoff automatically
using the source item's packaged desc as the CP-*'s content.

Idempotent — checks Cypra-PAA's board for an existing CP-* referencing the
source item before minting. Safe to fire on every PATCH of a matching item.

Insertion point: `_maybe_auto_mint_writeup_handoff` is called from the
PATCH /api/board/{id} handler after DB commit, alongside the other C3/C4
hooks (see `_auto_apply_adjudication`, `_auto_verify_from_audit_pair`,
`_auto_on_build_verify_close`).

Input contract:
    ctx = {
        "source_item_id": "CS-30",           # the writeup board item id
        "sampling_mode":  True,              # default True during rollout —
                                             # CP-* title prefixed [AUTO-HANDOFF]
                                             # and desc carries a sampling note
        "dry_run":        False,             # skip the mint (for tests)
        "_board_items":   [...],             # for tests: skip board fetch
    }

Output:
    {
        "action":       "minted" | "dry-run" | "skipped-duplicate" | "no-op",
        "cp_id":        "CP-78",             # on success
        "client":       "NPP",
        "date":         "2026-07-04",
        "sampling_mode": True,
        "reason":       "<one-line explanation>",
    }
"""
from __future__ import annotations
import re
from workflows._amux_workflow import log, http_get, http_post, http_patch


META = {
    "name": "writeup_handoff_auto_mint",
    "description": (
        "Auto-mint the Cypra-PAA handoff when a Nightly billable-notes writeup "
        "source item PATCHes to review. Removes step 4 from agent responsibility "
        "— makes the writeup → PAA handoff deterministic. Idempotent via "
        "existing-CP-* lookup."
    ),
    "input_schema": {
        "source_item_id": "string",
        "sampling_mode": "bool",
        "dry_run": "bool",
    },
    "output_schema": {
        "action": "string",
        "cp_id": "string|null",
        "client": "string",
        "date": "string",
        "sampling_mode": "bool",
        "reason": "string",
    },
}


WRITEUP_TITLE_PREFIX = "Nightly billable-notes writeup:"
CYPRA_SESSION = "Cypra-PAA"

# Bound on how many M-ids we resolve for the date sanity check. Very chatty
# writeups can cite dozens of messages; fetching them all serially would slow
# the hook. 20 covers a typical light-medium day writeup and is cheap.
MAX_MSG_IDS_TO_CHECK = 20

# PAA writes an outcome-code line to the source desc after reconciliation
# (LOGGED — 0h no activity, STAGED — ..., NEEDS REVIEW — ..., SKIPPED — ...).
# Presence of any of these means PAA already closed the loop; a hook fire
# post-outcome would be a duplicate mint attempt.
OUTCOME_CODE_PATTERN = re.compile(
    r"(?m)^\s*(LOGGED|STAGED|NEEDS[-\s]REVIEW|SKIPPED)\s*[—–-]", re.MULTILINE
)


def _extract_client_and_date(title: str) -> tuple[str, str]:
    """'Nightly billable-notes writeup: NPP — 2026-07-04' → ('NPP', '2026-07-04').

    Fallbacks: empty date if the trailing date is missing; whole
    post-colon fragment as client if the em-dash split fails.
    """
    date = ""
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})\s*$", title)
    if date_m:
        date = date_m.group(1)
    client = title
    m = re.match(rf"{re.escape(WRITEUP_TITLE_PREFIX)}\s*(.+?)\s*[—–-]\s*\d{{4}}-\d{{2}}-\d{{2}}", title)
    if m:
        client = m.group(1).strip()
    else:
        # Fallback: everything after "writeup:" up to the em-dash or end
        m = re.match(rf"{re.escape(WRITEUP_TITLE_PREFIX)}\s*(.+?)(?:\s*[—–-]\s*.*)?$", title)
        if m:
            client = m.group(1).strip()
    return client, date


def _scan_date_misattributions(desc: str, claimed_date: str, http_get_fn=None) -> list:
    """Spot-check that any M-\\d+ cited in the writeup desc has a `created`
    timestamp within the claimed report date's UTC window.

    Cypra-PAA caught CD-Shurloc misattributing 07-03 wrap-up work as 07-04
    via a Threads cross-check (07-04). This bakes the same check into the
    handoff mint so the misattribution surfaces at handoff time instead of
    at PAA reconciliation 8+ hours later.

    Returns a list of misattribution dicts:
        {"mid": "M-201", "cited_for": "2026-07-04", "actual_date": "2026-07-03", "delta_hrs": 5.5}

    Non-blocking — a returned non-empty list becomes a WARNING banner on
    the CP-*, not a failed mint. Cypra still sees the CP-*, just with the
    mismatch explicit at the top.

    Bounded to MAX_MSG_IDS_TO_CHECK unique M-ids to avoid slow paths on
    very chatty writeups. If a chatty writeup has more misattributions
    than the cap, we'll still catch the first N — enough signal for Cypra
    to decide the writeup needs a full manual review.
    """
    if not claimed_date or not desc:
        return []
    if http_get_fn is None:
        http_get_fn = http_get
    # Extract unique M-ids in order of first appearance.
    seen = []
    for m in re.finditer(r"\bM-(\d+)\b", desc):
        mid = f"M-{m.group(1)}"
        if mid not in seen:
            seen.append(mid)
        if len(seen) >= MAX_MSG_IDS_TO_CHECK:
            break
    if not seen:
        return []
    # Parse claimed date as a UTC window.
    try:
        from datetime import datetime, timezone, timedelta
        cd = datetime.strptime(claimed_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        window_start = cd
        window_end = cd + timedelta(days=1)
    except Exception:
        return []
    mismatches = []
    for mid in seen:
        try:
            msg = http_get_fn(f"/api/messages/{mid}")
        except Exception:
            continue  # message fetch errored — skip, do not block mint
        if msg.get("error"):
            continue  # message doesn't exist — skip
        created = msg.get("created")
        if not created:
            continue
        try:
            actual = datetime.fromtimestamp(int(created), tz=timezone.utc)
        except Exception:
            continue
        if window_start <= actual < window_end:
            continue  # inside the claimed window — OK
        # Misattributed. Record actual date + delta.
        delta = (actual - cd).total_seconds() / 3600.0
        mismatches.append({
            "mid": mid,
            "cited_for": claimed_date,
            "actual_date": actual.strftime("%Y-%m-%d"),
            "actual_ts_utc": actual.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "delta_hrs": round(delta, 1),
        })
    return mismatches


def _find_existing_handoff(source_item_id: str, board_items: list) -> dict | None:
    """Idempotency: return an existing CP-* on Cypra-PAA that was minted as a
    handoff of this exact source item.

    Match is TIGHT — looks for the `SOURCE_ITEM:` marker written only by real
    handoff mints (both the manual amux-helper relays and this workflow).
    A loose 'source_id anywhere in desc' match would false-fire on Cypra's
    silence-audit CP-*s that list missing source ids by name.
    """
    if not source_item_id:
        return None
    marker = f"SOURCE_ITEM:"
    for item in board_items:
        if not item.get("id", "").startswith("CP-"):
            continue
        if item.get("session") != CYPRA_SESSION:
            continue
        desc = item.get("desc", "") or ""
        if marker not in desc:
            continue
        # Confirm the marker line ends with our source_item_id
        if re.search(rf"SOURCE_ITEM:\s*{re.escape(source_item_id)}\b", desc):
            return item
    return None


def run(ctx: dict) -> dict:
    source_id = ctx.get("source_item_id", "").strip()
    sampling_mode = bool(ctx.get("sampling_mode", True))
    dry_run = bool(ctx.get("dry_run", False))
    if not source_id:
        log("run.abort", {"reason": "missing source_item_id"})
        return {"action": "no-op", "cp_id": None, "client": "", "date": "",
                "sampling_mode": sampling_mode, "reason": "missing source_item_id"}

    log("run.begin", {"source_id": source_id, "sampling_mode": sampling_mode})

    src = http_get(f"/api/board/{source_id}")
    if src.get("error"):
        log("run.abort", {"reason": f"source not found: {src.get('error')}"})
        return {"action": "no-op", "cp_id": None, "client": "", "date": "",
                "sampling_mode": sampling_mode, "reason": f"source not found: {src.get('error')}"}

    title = src.get("title", "") or ""
    if not title.startswith(WRITEUP_TITLE_PREFIX):
        log("run.skip", {"reason": "title does not match writeup prefix"})
        return {"action": "no-op", "cp_id": None, "client": "", "date": "",
                "sampling_mode": sampling_mode,
                "reason": f"title does not match {WRITEUP_TITLE_PREFIX!r} prefix"}

    # PAA-outcome guard: if the source desc already carries a PAA outcome
    # code (LOGGED / STAGED / NEEDS REVIEW / SKIPPED), the reconciliation
    # loop is already closed — a mint here would be a duplicate. Highest-
    # priority guard so it fires before the network hop for the board list.
    src_desc_for_check = src.get("desc", "") or ""
    outcome_m = OUTCOME_CODE_PATTERN.search(src_desc_for_check)
    if outcome_m:
        log("outcome_guard.skip", {"code": outcome_m.group(1)})
        return {"action": "skipped-outcome-closed", "cp_id": None,
                "client": "", "date": "", "sampling_mode": sampling_mode,
                "reason": f"PAA outcome '{outcome_m.group(1)}' already on source — loop is closed"}

    # Handoff-completion marker guard: if THIS workflow already ran against
    # this source and wrote its completion marker, don't re-mint. Belt-and-
    # suspenders vs. the board-lookup idempotency below (survives Cypra
    # rewriting the CP-* desc during reconciliation).
    if "[handoff auto-minted" in src_desc_for_check and "writeup_handoff_auto_mint" in src_desc_for_check:
        log("handoff_marker.skip", {})
        return {"action": "skipped-marker", "cp_id": None,
                "client": "", "date": "", "sampling_mode": sampling_mode,
                "reason": "source desc already carries a handoff-completion marker"}

    # Idempotency check — has this source already been handed off?
    board_items = ctx.get("_board_items")
    if board_items is None:
        try:
            board_items = http_get("/api/board?done_limit=200")
            if not isinstance(board_items, list):
                board_items = []
        except Exception as e:
            log("board.fetch.failed", {"err": str(e)[:120]})
            board_items = []
    existing = _find_existing_handoff(source_id, board_items)
    if existing:
        log("idempotent.skip", {"existing_cp": existing.get("id"),
                                "existing_title": existing.get("title", "")[:60]})
        return {"action": "skipped-duplicate", "cp_id": existing.get("id"),
                "client": "", "date": "", "sampling_mode": sampling_mode,
                "reason": f"already handed off as {existing.get('id')}"}

    client, date = _extract_client_and_date(title)
    src_desc = src.get("desc", "") or ""
    src_session = src.get("session", "") or ""

    # Date-sanity check on cited M-ids. Non-blocking — a warning gets prepended
    # to the CP-* desc and the misattributions come back in signals; the mint
    # still happens so Cypra sees the CP-* with the mismatch explicit at top.
    misattributions = _scan_date_misattributions(src_desc, date)
    if misattributions:
        log("date_sanity.warn", {"count": len(misattributions),
                                 "first": misattributions[0]})

    handoff_title_prefix = "[AUTO-HANDOFF] " if sampling_mode else ""
    if misattributions:
        handoff_title_prefix += "⚠ "
    handoff_title = f"{handoff_title_prefix}Nightly billable notes: {client} — {date}"

    sampling_note = ""
    if sampling_mode:
        sampling_note = (
            "\n\nSAMPLING MODE: this CP-* was auto-minted by writeup_handoff_auto_mint "
            "from the source writeup. During rollout, verify the source content maps "
            "correctly (right client, right date, packaged notes intact). If the "
            "auto-mint fired wrong, reopen the source item ({src}) with a reason and "
            "amux-helper will fold the fix. Once trust is established, sampling_mode "
            "flips off and future auto-mints drop the [AUTO-HANDOFF] prefix."
        ).format(src=source_id)

    # Warning banner prepended when any cited M-id lands outside the
    # claimed report window. Structured so Cypra can see at a glance
    # which mids and when they actually landed.
    warning_banner = ""
    if misattributions:
        warning_lines = [
            "⚠ DATE-SANITY WARNING (writeup_handoff_auto_mint, non-blocking)",
            f"⚠ {len(misattributions)} cited message id(s) fall outside the claimed report date "
            f"({date}). Spot-check the writeup before accepting the hours:",
            "",
        ]
        for mm in misattributions:
            warning_lines.append(
                f"  • {mm['mid']}  cited-for {mm['cited_for']}, actually created "
                f"{mm['actual_ts_utc']} ({mm['actual_date']}, Δ {mm['delta_hrs']:+.1f}h)"
            )
        warning_lines.append("")
        warning_lines.append(
            "⚠ Mint proceeded (warning-not-gate). If the writeup is wrong, reopen the "
            f"source item ({source_id}) with a reason and amux-helper will fold the "
            "pattern into the sanity check."
        )
        warning_banner = "\n".join(warning_lines) + "\n\n"

    handoff_desc = (
        f"{warning_banner}"
        f"[auto-handoff minted from {source_id} on {src_session} via writeup_handoff_auto_mint workflow]"
        f"{sampling_note}\n\n"
        f"=== PACKAGED BILLABLE NOTES (from {source_id}) ===\n"
        f"SOURCE_SESSION: {src_session}\n"
        f"SOURCE_ITEM:    {source_id}\n\n"
        f"{src_desc}"
    )

    if dry_run:
        log("dry_run.skip", {"would_title": handoff_title, "client": client, "date": date})
        return {"action": "dry-run", "cp_id": None, "client": client, "date": date,
                "sampling_mode": sampling_mode,
                "misattributions": misattributions,
                "reason": f"would mint {handoff_title!r} on {CYPRA_SESSION}"}

    handoff = http_post("/api/board", {
        "title": handoff_title,
        "session": CYPRA_SESSION,
        "status": "todo",
        "desc": handoff_desc,
    })
    cp_id = handoff.get("id", "")
    log("minted", {"cp_id": cp_id, "client": client, "date": date,
                   "misattributions_count": len(misattributions)})

    # Write a completion marker to the source desc so a future hook fire
    # sees the handoff has already been done and skips. Survives Cypra
    # rewriting the CP-* desc during reconciliation (source desc is on
    # the CD-* board, out of PAA's rewrite path).
    try:
        import time
        stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        completion_note = (
            f"\n\n[handoff auto-minted {stamp} by writeup_handoff_auto_mint → {cp_id}"
            f"{' with ' + str(len(misattributions)) + ' date-sanity warning(s)' if misattributions else ''}]"
        )
        http_patch(f"/api/board/{source_id}",
                   {"desc": (src.get("desc", "") or "") + completion_note})
    except Exception as _e:
        log("completion_marker.write_failed", {"err": str(_e)[:120]})
    return {"action": "minted", "cp_id": cp_id, "client": client, "date": date,
            "sampling_mode": sampling_mode,
            "misattributions": misattributions,
            "reason": f"minted {cp_id} on {CYPRA_SESSION}"
                      + (f" with {len(misattributions)} date-sanity warning(s)"
                         if misattributions else "")}
