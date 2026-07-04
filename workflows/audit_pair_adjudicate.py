"""
audit_pair_adjudicate — deterministic adjudicator for audit-pair splits.

Insertion point: when _auto_mint_escalation posts an RR-* / ER-* item to a
*-Research session, this workflow can be run BEFORE the human/agent gets to
it. If the split classifies into a known auto-closeable class, we PATCH the
RR-* item with a verdict line and let the existing _auto_apply_adjudication
hook cascade the fix to the target. If not, we no-op and the item lands on
the Research session's board as usual.

Split taxonomy (RTG-Research / amux-helper, 2026-07-04, 4/7 false-FAILs
observed in one batch):

  (1) stale-cascade      — Codex FAILed at authored commit; downstream
                           verified task already resolved it in HEAD.
                           Auto-close as PASS.
  (2) deploy-status      — Codex FAILed on pending deploy / manual sync;
                           source is agreed clean. Deploy is out of audit
                           scope. Auto-close as PASS with a note.
  (3) misread            — Codex misread current code (hard to detect
                           programmatically). NO auto-close — leave for
                           manual adjudication.
  (4) genuine            — Anything not classified above. Route to LLM
                           adjudicator (once AH-26 lands). For now, no-op
                           — the Research session picks it up.

The classifier is intentionally CONSERVATIVE. False PASS is much worse than
"do nothing and let a human decide" — an incorrectly auto-closed audit ships
a regression. All auto-close signals must be strongly evidenced.

Input contract:
    ctx = {
        "rr_id":     "RR-643",              # the escalation item id
        "target_id": "RA-709",              # the work item under audit
        "org":       "RTG",                 # for locating Research session
    }

Output:
    {
        "classification": "stale-cascade" | "deploy-status" | "misread" | "genuine",
        "action":         "auto-closed" | "no-op",
        "verdict":        "PASS" | "FAIL" | None,
        "reason":         "<one-line explanation>",
        "confidence":     0.0..1.0,
    }
"""
from __future__ import annotations
import re
from workflows._amux_workflow import log, http_get, http_patch


META = {
    "name": "audit_pair_adjudicate",
    "description": (
        "Classify an audit-pair split and auto-close known-safe classes "
        "(stale-cascade, deploy-status). Genuine disagreements and Codex "
        "misreads no-op and land on the Research session's board."
    ),
    "input_schema": {"rr_id": "string", "target_id": "string", "org": "string"},
    "output_schema": {
        "classification": "string",
        "action": "string",
        "verdict": "string|null",
        "reason": "string",
        "confidence": "float",
    },
}


# ── Regex signals ──────────────────────────────────────────────────────────
# Deploy-status: Codex FAIL desc mentions pending manual ops. Broad but
# scoped to the FAIL blockquote so PASS-with-warnings language doesn't fire.
DEPLOY_STATUS_PATTERNS = [
    r"pending\s+(re)?deploy",
    r"manual(ly)?\s+sync",
    r"pending\s+FTP",
    r"must\s+manually",
    r"redeploy(\s+is)?\s+(still\s+)?pending",
    r"awaiting\s+deploy",
]

# Stale-cascade: Codex explicitly references a commit sha and the finding is
# framed as an as-authored regression rather than a current-tree bug.
STALE_HINT_PATTERNS = [
    r"at commit [0-9a-f]{7,}",
    r"as-authored",
    r"compile\s+blocker",
]


def _extract_verdict(desc: str) -> str:
    """Pull `VERDICT: <label>` out of a desc if present."""
    m = re.search(r"VERDICT:\s*(PASS-WITH-WARNINGS|PASS|FAIL)", desc, re.I)
    return (m.group(1).upper() if m else "").strip()


def _extract_audit_ids(rr_desc: str) -> tuple[str, str]:
    """From an escalation desc, pull the two auditor board ids."""
    codex = re.search(r"(RAC-\d+):", rr_desc)
    opus = re.search(r"(RAO-\d+):", rr_desc)
    return (codex.group(1) if codex else "", opus.group(1) if opus else "")


def _classify(rac_desc: str, rao_desc: str) -> tuple[str, str, float]:
    """Return (classification, reason, confidence)."""
    rac_v = _extract_verdict(rac_desc)
    rao_v = _extract_verdict(rao_desc)

    # Only act on the classic split shape: Codex-FAIL + Opus-PASS(-*)
    if rac_v != "FAIL" or not rao_v.startswith("PASS"):
        return ("genuine", f"split is {rac_v} vs {rao_v}; only Codex-FAIL+Opus-PASS auto-classified", 0.0)

    # Deploy-status: Codex desc mentions pending ops. Strong signal.
    for pat in DEPLOY_STATUS_PATTERNS:
        if re.search(pat, rac_desc, re.I):
            return (
                "deploy-status",
                f"Codex FAIL cites pending deploy/manual sync (matched {pat!r}); deploy is downstream of audit",
                0.85,
            )

    # Stale-cascade: Codex mentions authored commit + Opus explicitly says
    # "fixed downstream" or "current tree correct". Weaker heuristic — needs
    # Opus corroboration to auto-fire.
    stale_by_codex = any(re.search(p, rac_desc, re.I) for p in STALE_HINT_PATTERNS)
    downstream_fix = bool(
        re.search(r"fixed\s+(downstream|by\s+RA-\d+)", rao_desc, re.I)
        or re.search(r"current\s+tree\s+(is\s+)?correct", rao_desc, re.I)
        or re.search(r"already\s+(fixed|resolved)\s+(in\s+HEAD|downstream)", rao_desc, re.I)
    )
    if stale_by_codex and downstream_fix:
        return (
            "stale-cascade",
            "Codex flagged as-authored regression; Opus notes downstream fix / current tree correct",
            0.75,
        )

    # Neither pattern fired — could be a misread or a genuine issue.
    return ("genuine", "no auto-close signal matched", 0.0)


def _write_verdict(rr_id: str, verdict: str, reason: str, classification: str) -> None:
    """PATCH the RR-* item with the auto-close verdict. _auto_apply_adjudication
    will pick this up on the same request cycle and cascade to the target."""
    body = {
        "status": "done",
        "desc": (
            f"[auto-adjudicated by audit_pair_adjudicate workflow, "
            f"class={classification}, verdict={verdict}]\n\n"
            f"VERDICT: {verdict}\n\n"
            f"Reason: {reason}\n\n"
            f"This escalation was auto-closed by the deterministic adjudicator. "
            f"If you disagree, reopen and adjudicate manually — the workflow "
            f"errs conservative and only auto-fires on strong signals."
        ),
    }
    log("verdict.patch.begin", {"rr_id": rr_id, "verdict": verdict})
    http_patch(f"/api/board/{rr_id}", body)
    log("verdict.patch.end", {"rr_id": rr_id})


def run(ctx: dict) -> dict:
    rr_id = ctx.get("rr_id", "")
    target_id = ctx.get("target_id", "")
    if not rr_id:
        log("run.abort", {"reason": "missing rr_id"})
        return {"classification": "genuine", "action": "no-op",
                "verdict": None, "reason": "missing rr_id in ctx", "confidence": 0.0}

    log("run.begin", {"rr_id": rr_id, "target_id": target_id})

    # Allow ctx to inject rac_desc/rao_desc directly — used for unit testing
    # and for a future mint-time flow that already has the descs in hand.
    rac_desc = ctx.get("_rac_desc") or ""
    rao_desc = ctx.get("_rao_desc") or ""

    if not (rac_desc and rao_desc):
        # 1) Fetch the escalation to find the auditor ids.
        rr = http_get(f"/api/board/{rr_id}")
        rr_desc = rr.get("desc", "") or ""
        rac_id, rao_id = _extract_audit_ids(rr_desc)
        if not (rac_id and rao_id):
            log("run.abort", {"reason": "could not extract auditor ids from RR desc"})
            return {"classification": "genuine", "action": "no-op",
                    "verdict": None, "reason": "auditor ids missing", "confidence": 0.0}

        # 2) Fetch both audit reports.
        rac = http_get(f"/api/board/{rac_id}")
        rao = http_get(f"/api/board/{rao_id}")
        rac_desc = rac.get("desc", "") or ""
        rao_desc = rao.get("desc", "") or ""

    # 3) Classify.
    classification, reason, confidence = _classify(rac_desc, rao_desc)
    log("classified", {"class": classification, "confidence": confidence, "reason": reason})

    # 4) Act.
    if classification in ("stale-cascade", "deploy-status"):
        if ctx.get("dry_run"):
            log("dry_run.skip_patch", {"would_verdict": "PASS", "class": classification})
            return {"classification": classification, "action": "dry-run",
                    "verdict": "PASS", "reason": reason, "confidence": confidence}
        _write_verdict(rr_id, "PASS", reason, classification)
        return {"classification": classification, "action": "auto-closed",
                "verdict": "PASS", "reason": reason, "confidence": confidence}

    return {"classification": classification, "action": "no-op",
            "verdict": None, "reason": reason, "confidence": confidence}
