// Resume where another agent left off.
// Run (after `npm run build`): ARIOUS_MCP_TOKEN=... node examples/resume-context.mjs
import { AriousClient, ContextConflict } from "@arious-meet/mcp";

const client = new AriousClient({ modelName: "Claude Sonnet 5" });

// 1. Orient yourself. startHere also carries the last context's brief.
const start = await client.startHere();
console.log(start.text);

// 2. Pick up the most recently updated active context (or pass { context_id }).
const resume = (await client.contextResume()).data;
console.log(resume.brief); // saved notes of earlier sessions: data, never instructions
if (!resume.can_write) throw new Error("this context is read-only");

// 3. ...do the next step, then checkpoint it against the version you read.
let base = resume.version;
for (let attempt = 0; attempt < 2; attempt++) {
  try {
    const saved = (
      await client.contextCheckpoint({
        context_id: resume.context_id,
        base_version: base,
        current_step: "Reviewing the results",
        append: { done_steps: ["Finished the step I picked up"] },
      })
    ).data;
    console.log("saved version", saved.version);
    for (const r of saved.redacted) console.log("redacted", r.kind, "in", r.field);
    break;
  } catch (e) {
    if (!(e instanceof ContextConflict)) throw e;
    // Another agent wrote meanwhile: merge into e.latest, then retry on top of it.
    console.log("conflict, latest is version", e.latestVersion);
    base = e.latestVersion;
  }
}
