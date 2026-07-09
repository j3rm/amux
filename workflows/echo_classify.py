"""
echo_classify — tiniest possible workflow. Proves the plumbing.

Takes a string in ctx["text"], classifies it into one of three buckets
using deterministic Python (no LLM), returns the classification.

Useful as a template for authors and as a smoke test for the runner.

Run:
    POST /api/workflows/echo_classify/run
    body: {"ctx": {"text": "urgent server down"}}
    → {"category": "urgent", "keyword": "urgent", "text_len": 17}
"""
from workflows._amux_workflow import log


META = {
    "name": "echo_classify",
    "description": "Classify a string into urgent/question/info via keyword match.",
    "input_schema": {"text": "string"},
    "output_schema": {"category": "string", "keyword": "string", "text_len": "int"},
}


def run(ctx: dict) -> dict:
    text = str(ctx.get("text", "")).lower().strip()
    log("classify.begin", {"text_len": len(text)})

    URGENT = ("urgent", "critical", "down", "outage", "halt", "blocked")
    QUESTION = ("?", "how", "why", "what", "when", "where")

    matched = ""
    category = "info"
    for kw in URGENT:
        if kw in text:
            matched, category = kw, "urgent"
            break
    if not matched:
        for kw in QUESTION:
            if kw in text:
                matched, category = kw, "question"
                break

    log("classify.end", {"category": category, "keyword": matched})
    return {"category": category, "keyword": matched, "text_len": len(text)}
