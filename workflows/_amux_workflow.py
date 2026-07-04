"""
_amux_workflow — tiny helpers for authoring amux workflow modules.

A workflow is a plain Python module with a `run(ctx: dict) -> dict` function.
Some steps are pure Python (deterministic classifiers, applies, guards);
some steps are LLM invocations against a pinned system+prompt with no
carried-over session state.

Design intent (contrast with a DAG/DSL approach):
- Just Python. No graph builder, no schema, no runtime magic. If your
  workflow is control flow, write control flow.
- LLM calls flow through `llm.invoke(...)` so we can (a) route them
  centrally, (b) instrument token spend per purpose (later — see AH-27),
  (c) fall back gracefully when the server is restarting.
- Every step should be small enough to test in isolation and idempotent
  where possible. If the workflow crashes mid-run, re-running with the
  same input should be safe.

The `log()` helper emits step-level events that the server persists to the
workflow_runs table so a run can be inspected after the fact.
"""
from __future__ import annotations
import json
import os
import ssl
import time
import urllib.request
from typing import Any, Callable


# ── Ambient state — filled in by the runner before calling into run(ctx) ────
_current_run_id: str = ""
_step_events: list = []
_amux_url: str = os.environ.get("AMUX_URL", "https://localhost:8822")
_ctx: ssl.SSLContext = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _auth_headers() -> dict:
    """Reads the amux auth token from disk. Workflows run in-process on the
    same box as the server, so this is the equivalent of talking to a local
    unix socket — no privilege escalation. Header keyed as the server expects.
    """
    hdrs = {"Content-Type": "application/json"}
    try:
        token_path = os.path.expanduser("~/.amux/auth_token")
        with open(token_path) as f:
            hdrs["Authorization"] = "Bearer " + f.read().strip()
    except Exception:
        pass
    return hdrs


def _set_run(run_id: str) -> None:
    """Called by the runner before executing a workflow. Not user-facing."""
    global _current_run_id, _step_events
    _current_run_id = run_id
    _step_events = []


def _drain_events() -> list:
    """Called by the runner after execution to persist step events."""
    global _step_events
    events = _step_events
    _step_events = []
    return events


def log(kind: str, data: dict | None = None) -> None:
    """Emit a step-level event. Persisted to the run record.

    Use liberally — cheap, and the transcript is what makes a workflow
    debuggable after the fact.
    """
    _step_events.append({
        "ts": int(time.time()),
        "kind": kind,
        "data": data or {},
    })


class _LLM:
    """Namespaced entry point for LLM invocations from a workflow step.

    Currently uses `curl` semantics against the workflow's own process to
    reach the amux server. When AH-26 (single-turn stateless LLM invoke
    API) lands, this will proxy through /api/llm/invoke and pick up
    automatic instrumentation. For now the shape is fixed so we don't
    have to rewrite call sites later.
    """

    def invoke(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        purpose: str,
        max_tokens: int = 2000,
    ) -> dict:
        """Fire a one-shot LLM call. No history, no state.

        `purpose` is a free-form tag (e.g. "audit-adjudicate") that
        instrumentation will roll up on (AH-27).

        Returns a dict with keys: `text`, `model`, `input_tokens`,
        `output_tokens`, `purpose`, `ts`.

        Placeholder implementation: routes through
        POST /api/llm/invoke which does not exist yet (AH-26). Until
        then, this raises NotImplementedError with a clear message so
        the workflow fails loud rather than silently producing wrong
        output.
        """
        log("llm.invoke.begin", {
            "purpose": purpose, "model": model, "prompt_bytes": len(prompt),
        })
        try:
            req = urllib.request.Request(
                f"{_amux_url}/api/llm/invoke",
                data=json.dumps({
                    "model": model,
                    "system": system,
                    "prompt": prompt,
                    "purpose": purpose,
                    "max_tokens": max_tokens,
                }).encode(),
                method="POST",
                headers=_auth_headers(),
            )
            with urllib.request.urlopen(req, context=_ctx, timeout=120) as r:
                result = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotImplementedError(
                    "llm.invoke requires /api/llm/invoke (AH-26, not yet built). "
                    "Until it lands, either mock this step or run the LLM call "
                    "manually and pass the result through ctx."
                ) from e
            raise
        log("llm.invoke.end", {
            "purpose": purpose,
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
        })
        return result


llm = _LLM()


def http_post(path: str, body: dict) -> dict:
    """POST to the amux server with the same retry-safety as the CLI stub."""
    for delay in (0, 2, 5):
        if delay:
            time.sleep(delay)
        try:
            req = urllib.request.Request(
                f"{_amux_url}{path}",
                data=json.dumps(body).encode(),
                method="POST",
                headers=_auth_headers(),
            )
            with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            log("http_post.retry", {"path": path, "err": str(e)[:120]})
    raise RuntimeError(f"http_post failed after retries: {path}")


def http_patch(path: str, body: dict) -> dict:
    for delay in (0, 2, 5):
        if delay:
            time.sleep(delay)
        try:
            req = urllib.request.Request(
                f"{_amux_url}{path}",
                data=json.dumps(body).encode(),
                method="PATCH",
                headers=_auth_headers(),
            )
            with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            log("http_patch.retry", {"path": path, "err": str(e)[:120]})
    raise RuntimeError(f"http_patch failed after retries: {path}")


def http_get(path: str) -> dict:
    """GET from the amux server. Single-shot; reads are cheap to retry from caller."""
    req = urllib.request.Request(f"{_amux_url}{path}", headers=_auth_headers())
    with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
        return json.loads(r.read())
