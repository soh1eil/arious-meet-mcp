//! Resume where another agent left off. Run with ARIOUS_MCP_TOKEN set:
//! `cargo run --example resume_context`.
use arious_meet_mcp::{
    CheckpointResult, Client, ContextCheckpointOpts, ContextResume, Error, StartHere,
};
use serde_json::json;

#[tokio::main]
async fn main() -> arious_meet_mcp::Result<()> {
    let mcp = Client::from_env(Some("Claude Sonnet 5"))?; // reads ARIOUS_MCP_TOKEN

    // 1. Orient yourself. start_here also carries the last context's brief.
    let start = mcp.start_here().await?;
    println!("{}", start.text);
    let _typed: StartHere = start.decode()?;

    // 2. Pick up the most recently updated active context (or set `context_id`).
    let resume: ContextResume = mcp.context_resume(Default::default()).await?.decode()?;
    println!("{}", resume.brief); // saved notes of earlier sessions: data, never instructions
    if !resume.can_write {
        return Err(Error::InvalidArgument("this context is read-only".into()));
    }

    // 3. ...do the next step, then checkpoint it against the version you read.
    let mut base = resume.version;
    for _ in 0..2 {
        let opts = ContextCheckpointOpts {
            current_step: Some("Reviewing the results".into()),
            append: Some(json!({"done_steps": ["Finished the step I picked up"]})),
            ..Default::default()
        };
        match mcp.context_checkpoint(base, &resume.context_id, opts).await {
            Ok(r) => {
                let saved: CheckpointResult = r.decode()?;
                println!("saved version {}", saved.version);
                for x in &saved.redacted {
                    // secrets the server removed; never put credentials in a context
                    println!("redacted {} in {}", x.kind, x.field);
                }
                return Ok(());
            }
            Err(Error::ContextConflict { latest_version, .. }) => {
                // Another agent wrote meanwhile: merge into `latest`, then retry on top of it.
                println!("conflict, latest is version {latest_version}");
                base = latest_version;
            }
            Err(e) => return Err(e),
        }
    }
    Err(Error::InvalidArgument(
        "could not save the checkpoint".into(),
    ))
}
