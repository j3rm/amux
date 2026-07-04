"""amux workflows — Python-first deterministic multi-agent choreographies.

Each *.py module (not starting with _) exposes:
    run(ctx: dict) -> dict     — the workflow body
    META: dict                  — name, description, input/output schemas

See _amux_workflow.py for the helper module (llm.invoke, log, http_*).
See echo_classify.py for the smallest working example.
"""
