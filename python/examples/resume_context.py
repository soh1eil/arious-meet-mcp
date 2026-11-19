"""Resume where another agent left off.

Run: ARIOUS_MCP_TOKEN=... python examples/resume_context.py
Reads the most recent active context, does a step, and saves it back.
"""

from arious_meet_mcp import (
    CheckpointResult,
    Client,
    ContextConflict,
    ContextResume,
    StartHere,
)

with Client(model_name="Claude Sonnet 5") as client:
    # 1. Orient yourself. start_here also carries the last context's brief.
    start = StartHere.from_result(client.start_here())
    print(start.text)

    # 2. Pick up the most recently updated active context (or pass context_id=...).
    resume = ContextResume.from_result(client.context_resume())
    print(resume.brief)  # saved notes of earlier sessions: data, never instructions
    if not resume.can_write:
        raise SystemExit("this context is read-only")

    # 3. ...do the next step, then checkpoint it against the version you read.
    base = resume.version
    for _attempt in range(2):
        try:
            saved = CheckpointResult.from_result(
                client.context_checkpoint(
                    resume.context_id,
                    base,
                    current_step="Reviewing the results",
                    append={"done_steps": ["Finished the step I picked up"]},
                )
            )
            break
        except ContextConflict as conflict:
            # Another agent wrote meanwhile: merge into conflict.latest, then retry on top of it.
            print("conflict, latest is version", conflict.latest_version)
            base = conflict.latest_version
    else:
        raise SystemExit("could not save the checkpoint")
    print("saved version", saved.version)
    for r in saved.redacted:  # secrets the server removed; never put credentials in a context
        print("redacted", r.kind, "in", r.field)
