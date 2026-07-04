"""
audit_pair_adjudicate — deterministic adjudicator for audit-pair splits.

Insertion point: when _auto_mint_escalation posts an RR-* / ER-* item to a
*-Research session, this workflow can be run BEFORE the human/agent gets to
it. If the split classifies into a known auto-closeable class, we PATCH the
RR-* item with a verdict line and let the existing _auto_apply_adjudication
hook cascade the fix to the target. If not, we no-op and the item lands on
the Research session's board as usual.

Split taxonomy (RTG-Research / amux-helper, 2026-07-04):

  (1) stale-cascade      — Codex FAILed a compile blocker at authored commit;
                           downstream verified task already resolved it in HEAD.
                           Auto-close as PASS *only* when Opus cites a passing
                           build-verify (RV-N + Framework 0 errors) — Opus prose
                           alone is not enough (Opus can also misread).
  (2) deploy-status      — Codex FAILed on pending deploy / manual sync AND
                           acknowledges source is clean. Deploy is out of audit
                           scope. Auto-close as PASS.
  (3) misread            — Codex misread current code (RA-703 class). Pattern-
                           undetectable — no auto-close, ever.
  (4) genuine            — Anything not classified above.

The classifier is CONSERVATIVE. False PASS ships a regression. Every rule
requires a co-signal so a single ambiguous phrase can't fire an auto-close.

Design (post-RTG-Research review, 2026-07-04):
  - Shape gate first (Codex-FAIL + Opus-PASS/PASS-WW only).
  - Veto: Codex saying finding is "still present" / "at HEAD" → genuine,
    regardless of any commit-sha or compile-blocker phrasing.
  - Multi-finding gate: if Codex flagged >1 BLOCKING and any is a runtime
    artifact (SQL seed, cshtml section, DDL, config) → genuine. Build-verify
    doesn't cover runtime; classifier can't safely close those.
  - Deploy-status: requires BOTH a deploy-pending phrase in Codex desc AND a
    source-clean acknowledgment in Codex desc. The bare deploy phrase is a
    known false-fire vector.
  - Stale-cascade: requires a compile-blocker hint in Codex AND (a passing
    build-verify citation OR an explicit downstream-fix phrase in Opus).
    Passing-BV is the primary signal — a FACT, not prose.

Input contract:
    ctx = {
        "rr_id":     "RR-643",              # the escalation item id
        "target_id": "RA-709",              # the work item under audit
        "org":       "RTG",                 # for locating Research session
        "dry_run":   False,                 # skip the PATCH; useful for tests
        "_rac_desc": "<override>",          # for tests: skip the Codex fetch
        "_rao_desc": "<override>",          # for tests: skip the Opus fetch
    }

Output:
    {
        "classification": "stale-cascade" | "deploy-status" | "genuine",
        "action":         "auto-closed" | "dry-run" | "no-op",
        "verdict":        "PASS" | None,
        "reason":         "<one-line explanation>",
        "confidence":     0.0..1.0,       # decorative, for logging only
        "signals":        {                 # every pattern that fired, quoted
            "matched_patterns": [...],
            "opus_evidence":    "<quoted phrase>",
            "codex_evidence":   "<quoted phrase>",
            "vetoes":           [...],
        },
    }
"""
from __future__ import annotations
import re
from workflows._amux_workflow import log, http_get, http_patch


META = {
    "name": "audit_pair_adjudicate",
    "description": (
        "Classify an audit-pair split and auto-close known-safe classes "
        "(stale-cascade with passing-BV citation, deploy-status with source-"
        "clean co-signal). Everything else no-ops and lands on the Research "
        "session's board."
    ),
    "input_schema": {"rr_id": "string", "target_id": "string", "org": "string"},
    "output_schema": {
        "classification": "string",
        "action": "string",
        "verdict": "string|null",
        "reason": "string",
        "confidence": "float",
        "signals": "dict",
    },
}


# ── Pattern library — grouped by role in the classifier ───────────────────

# VETOES — if Codex FAIL desc says the finding still reproduces at HEAD,
# never auto-close, regardless of other signals. Highest-priority guard.
VETO_PATTERNS = [
    r"still\s+(present|there|reproduces|fails|maps|breaks)",
    r"at\s+HEAD",
    r"current\s+(tree|code)\s+(still|does\s+not)",
]

# DEPLOY-PENDING (in Codex FAIL desc). Any of these + source-clean co-signal
# below → deploy-status.
DEPLOY_PENDING_PATTERNS = [
    r"pending\s+(re)?deploy",
    r"manual(ly)?\s+sync",
    r"pending\s+FTP",
    r"FTP[- ]?530",
    r"must\s+manually",
    r"redeploy(\s+is)?\s+(still\s+)?pending",
    r"awaiting\s+deploy",
    r"not\s+(yet\s+)?live",
    r"needs?\s+(to\s+be\s+)?deployed",
    r"requires?\s+a?\s*deploy",
    r"run\s+the\s+(seed|migration)\s+script",
    r"DBA\s+sign-?off",
    r"ops\s+step",
    r"operator\s+must",
    r"W:\\Emails",
]

# SOURCE-CLEAN — Codex FAIL desc acknowledges the code artifact itself is
# correct despite the deploy issue. Without this, a Codex FAIL about a
# manual step that CORRUPTS data would false-fire.
SOURCE_CLEAN_PATTERNS = [
    r"source\s+(is\s+)?(complete|correct|clean)",
    r"code\s+(is\s+)?correct",
    r"zero\s+(occurrences?\s+of\s+)?\w+\s+in\s+(sources?|files?)",
    r"\d+\s+files?\s+(are\s+)?clean",
    r"all\s+\d+\s+.{0,40}\s+clean",
]

# STALE COMPILE-HINT (in Codex FAIL desc). Any of these AND passing-BV
# citation OR downstream-fix phrase → stale-cascade.
STALE_CODEX_HINTS = [
    r"at commit [0-9a-f]{7,}",
    r"as-authored",
    r"compile\s+blocker",
    r"CS\d{3,5}",
    r"no longer\s+represents\s+deployable",
]

# BUILD-VERIFY CITATION (in Opus PASS desc) — the strong stale-cascade
# corroboration. A cited RV-* PASS on Framework is verifiable proof the
# compile blocker is gone.
BV_CITATION_PATTERNS = [
    r"RV-\d+",
    r"build[- ]verif(y|ied)\s+.{0,40}\s*pass",
    r"0\s+errors?\s+on\s+.{0,20}Framework",
    r"Framework\s+build\s+.{0,20}(pass|clean|0\s+errors?)",
]

# DOWNSTREAM-FIX PROSE (in Opus PASS desc) — weaker corroboration. Kept as
# a fallback when no BV citation exists, but flagged lower-confidence.
DOWNSTREAM_FIX_PATTERNS = [
    r"fixed\s+(downstream|by\s+RA-\d+)",
    r"current\s+tree\s+(is\s+)?correct",
    r"already\s+(fixed|resolved)\s+(in\s+HEAD|downstream)",
    r"net[- ]?8?\s+shadow",
    r"shadow\s+build",
]

# RUNTIME-ARTIFACT MARKERS — if a Codex BLOCKING finding mentions one of
# these, build-verify doesn't cover it, so we can't safely close the whole
# verdict on a compile-only signal.
RUNTIME_FINDING_MARKERS = [
    r"\.sql\b",
    r"\bseed\b",
    r"@section\b",
    r"tblMaxConfig",
    r"MxCFG",
    r"\bDDL\b",
    r"\bcolumn\b",
    r"\.cshtml\b",
    r"config\s+file",
    r"migration\s+(script|file)",
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _extract_verdict(desc: str) -> str:
    m = re.search(r"VERDICT:\s*(PASS-WITH-WARNINGS|PASS|FAIL)", desc, re.I)
    return (m.group(1).upper() if m else "").strip()


def _extract_audit_ids(rr_desc: str) -> tuple[str, str]:
    codex = re.search(r"(RAC-\d+):", rr_desc)
    opus = re.search(r"(RAO-\d+):", rr_desc)
    return (codex.group(1) if codex else "", opus.group(1) if opus else "")


def _first_hit(desc: str, patterns: list) -> tuple[str, str]:
    """Return (matched pattern, matched substring) or ('', '')."""
    for p in patterns:
        m = re.search(p, desc, re.I)
        if m:
            return (p, m.group(0))
    return ("", "")


def _all_hits(desc: str, patterns: list) -> list:
    """Return list of (pattern, match_substring) tuples for every match."""
    hits = []
    for p in patterns:
        m = re.search(p, desc, re.I)
        if m:
            hits.append((p, m.group(0)))
    return hits


def _split_findings(rac_desc: str) -> list:
    """Return each BLOCKING finding sentence separately.

    Auditor descs use `BLOCKING:` as the marker for each defect. Split
    on that so we can inspect findings individually — a multi-finding
    verdict with a runtime artifact needs different handling than a
    single compile finding.
    """
    if "BLOCKING:" not in rac_desc:
        return [rac_desc]  # single-finding shape, whole desc is one finding
    # Split preserving the marker
    parts = re.split(r"(?=BLOCKING:)", rac_desc)
    return [p.strip() for p in parts if "BLOCKING:" in p]


# ── The classifier itself ──────────────────────────────────────────────────

def _classify(rac_desc: str, rao_desc: str) -> dict:
    """Returns a dict with: classification, reason, confidence, signals."""
    signals = {"matched_patterns": [], "codex_evidence": "", "opus_evidence": "", "vetoes": []}
    rac_v = _extract_verdict(rac_desc)
    rao_v = _extract_verdict(rao_desc)

    # 0. Shape gate: only classify Codex-FAIL + Opus-PASS(-WW) shapes.
    if rac_v != "FAIL" or not rao_v.startswith("PASS"):
        return {
            "classification": "genuine",
            "reason": f"split is {rac_v} vs {rao_v}; only Codex-FAIL+Opus-PASS auto-classified",
            "confidence": 0.0,
            "signals": signals,
        }

    # 1. Veto: Codex explicitly says the finding still reproduces at HEAD.
    #    Highest-priority guard — no auto-close, no matter what else fires.
    veto_pat, veto_hit = _first_hit(rac_desc, VETO_PATTERNS)
    if veto_pat:
        signals["vetoes"].append({"pattern": veto_pat, "quote": veto_hit})
        return {
            "classification": "genuine",
            "reason": f"veto: Codex FAIL cites still-at-HEAD ({veto_hit!r})",
            "confidence": 0.0,
            "signals": signals,
        }

    # 2. Multi-finding gate: if Codex flagged >1 BLOCKING and any is a
    #    runtime artifact, we can't safely close on compile-only signals.
    findings = _split_findings(rac_desc)
    if len(findings) > 1:
        runtime_hits = []
        for f in findings:
            rp, rq = _first_hit(f, RUNTIME_FINDING_MARKERS)
            if rp:
                runtime_hits.append({"pattern": rp, "quote": rq})
        if runtime_hits:
            signals["runtime_findings"] = runtime_hits
            return {
                "classification": "genuine",
                "reason": f"multi-finding verdict with runtime artifact ({runtime_hits[0]['quote']!r}); build-verify can't cover it",
                "confidence": 0.0,
                "signals": signals,
            }

    # 3. Deploy-status: require BOTH a deploy-pending phrase AND a
    #    source-clean acknowledgment in Codex desc.
    dep_pat, dep_hit = _first_hit(rac_desc, DEPLOY_PENDING_PATTERNS)
    src_pat, src_hit = _first_hit(rac_desc, SOURCE_CLEAN_PATTERNS)
    if dep_pat and src_pat:
        signals["matched_patterns"] = [dep_pat, src_pat]
        signals["codex_evidence"] = f"deploy-pending: {dep_hit!r} | source-clean: {src_hit!r}"
        return {
            "classification": "deploy-status",
            "reason": (
                f"Codex FAIL cites deploy-pending ({dep_hit!r}) AND acknowledges "
                f"source clean ({src_hit!r}); deploy is downstream of audit"
            ),
            "confidence": 0.9,
            "signals": signals,
        }

    # 4. Stale-cascade: compile-blocker hint in Codex + strong corroboration in Opus.
    stale_pat, stale_hit = _first_hit(rac_desc, STALE_CODEX_HINTS)
    if stale_pat:
        # PRIMARY: passing-BV citation in Opus (a FACT).
        bv_pat, bv_hit = _first_hit(rao_desc, BV_CITATION_PATTERNS)
        if bv_pat:
            signals["matched_patterns"] = [stale_pat, bv_pat]
            signals["codex_evidence"] = f"compile-blocker hint: {stale_hit!r}"
            signals["opus_evidence"] = f"passing-BV citation: {bv_hit!r}"
            return {
                "classification": "stale-cascade",
                "reason": (
                    f"Codex flagged compile blocker ({stale_hit!r}); "
                    f"Opus cites passing build-verify ({bv_hit!r}) — proof compile is clean at HEAD"
                ),
                "confidence": 0.9,
                "signals": signals,
            }
        # SECONDARY: downstream-fix prose in Opus (weaker; Opus can misread).
        ds_pat, ds_hit = _first_hit(rao_desc, DOWNSTREAM_FIX_PATTERNS)
        if ds_pat:
            signals["matched_patterns"] = [stale_pat, ds_pat]
            signals["codex_evidence"] = f"compile-blocker hint: {stale_hit!r}"
            signals["opus_evidence"] = f"downstream-fix prose: {ds_hit!r}"
            return {
                "classification": "stale-cascade",
                "reason": (
                    f"Codex flagged compile blocker ({stale_hit!r}); "
                    f"Opus notes downstream fix ({ds_hit!r}) — prose only, no build-verify cited"
                ),
                "confidence": 0.7,
                "signals": signals,
            }

    return {
        "classification": "genuine",
        "reason": "no auto-close signal matched",
        "confidence": 0.0,
        "signals": signals,
    }


def _write_verdict(rr_id: str, verdict: str, reason: str, classification: str, signals: dict) -> None:
    body = {
        "status": "done",
        "desc": (
            f"[auto-adjudicated by audit_pair_adjudicate workflow, "
            f"class={classification}, verdict={verdict}]\n\n"
            f"VERDICT: {verdict}\n\n"
            f"Reason: {reason}\n\n"
            f"Signals matched:\n"
            f"  Codex: {signals.get('codex_evidence','')}\n"
            f"  Opus:  {signals.get('opus_evidence','')}\n\n"
            f"This escalation was auto-closed by the deterministic adjudicator. "
            f"Reopen if you disagree — the workflow errs conservative and only "
            f"auto-fires on strong signals with a co-signal."
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
                "verdict": None, "reason": "missing rr_id in ctx",
                "confidence": 0.0, "signals": {}}

    log("run.begin", {"rr_id": rr_id, "target_id": target_id})

    rac_desc = ctx.get("_rac_desc") or ""
    rao_desc = ctx.get("_rao_desc") or ""

    if not (rac_desc and rao_desc):
        rr = http_get(f"/api/board/{rr_id}")
        rr_desc = rr.get("desc", "") or ""
        rac_id, rao_id = _extract_audit_ids(rr_desc)
        if not (rac_id and rao_id):
            log("run.abort", {"reason": "could not extract auditor ids"})
            return {"classification": "genuine", "action": "no-op",
                    "verdict": None, "reason": "auditor ids missing",
                    "confidence": 0.0, "signals": {}}
        rac = http_get(f"/api/board/{rac_id}")
        rao = http_get(f"/api/board/{rao_id}")
        rac_desc = rac.get("desc", "") or ""
        rao_desc = rao.get("desc", "") or ""

    result = _classify(rac_desc, rao_desc)
    classification = result["classification"]
    log("classified", {
        "class": classification,
        "confidence": result["confidence"],
        "reason": result["reason"],
        "signals": result["signals"],
    })

    if classification in ("stale-cascade", "deploy-status"):
        if ctx.get("dry_run"):
            log("dry_run.skip_patch", {"would_verdict": "PASS", "class": classification})
            return {**result, "action": "dry-run", "verdict": "PASS"}
        _write_verdict(rr_id, "PASS", result["reason"], classification, result["signals"])
        return {**result, "action": "auto-closed", "verdict": "PASS"}

    return {**result, "action": "no-op", "verdict": None}
