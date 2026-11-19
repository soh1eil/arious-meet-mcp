use std::future::Future;
use std::time::Duration;

use serde_json::Value;

use crate::client::{Client, ToolResult};
use crate::error::{Error, Result};
use crate::tools::{AckUpdatesOpts, GetUpdatesOpts, SendFileOpts};

/// Options for [`Client::watch_updates`].
#[derive(Debug, Clone)]
pub struct WatchOptions {
    /// Kinds to hear about (`mention`, `direct_message`, ...); `None` = everything.
    pub only: Option<Vec<String>>,
    /// Long-poll seconds, 0-25.
    pub wait_seconds: i64,
    /// Pause after a transient failure (multiplied up to 5x).
    pub idle_backoff: Duration,
}

impl Default for WatchOptions {
    fn default() -> Self {
        Self {
            only: None,
            wait_seconds: 25,
            idle_backoff: Duration::from_secs(2),
        }
    }
}

impl Client {
    /// Long-polls `get_updates` and calls `handler` for every update. The
    /// handler returns `true` to keep going, `false` to stop. After a batch
    /// has been fully handled the cursor is acknowledged with `ack_updates`,
    /// so a crash mid-batch re-delivers instead of losing items.
    ///
    /// Rate limits and transient network errors back off and continue;
    /// authentication errors end the loop with the error.
    pub async fn watch_updates<F, Fut>(&self, opts: WatchOptions, mut handler: F) -> Result<()>
    where
        F: FnMut(Value) -> Fut,
        Fut: Future<Output = bool>,
    {
        let mut cursor: Option<String> = None;
        let mut failures: u32 = 0;
        loop {
            let r = self
                .get_updates(GetUpdatesOpts {
                    only: opts.only.clone(),
                    wait_seconds: Some(opts.wait_seconds),
                    cursor: cursor.clone(),
                    ..Default::default()
                })
                .await;
            let r = match r {
                Ok(r) => {
                    failures = 0;
                    r
                }
                Err(e @ Error::Auth { .. }) => return Err(e),
                Err(Error::RateLimit { retry_after, .. }) => {
                    tokio::time::sleep(retry_after.unwrap_or(opts.idle_backoff)).await;
                    continue;
                }
                Err(Error::Transport { .. }) => {
                    failures += 1;
                    tokio::time::sleep(opts.idle_backoff * failures.min(5)).await;
                    continue;
                }
                Err(e) => return Err(e),
            };
            let data = r.data();
            let updates = data
                .get("updates")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let next = data
                .get("next_cursor")
                .and_then(Value::as_str)
                .map(str::to_string)
                .filter(|s| !s.is_empty());
            for u in &updates {
                if !handler(u.clone()).await {
                    return Ok(());
                }
            }
            if let Some(n) = next {
                if !updates.is_empty() {
                    self.ack_updates(AckUpdatesOpts {
                        cursor: Some(n.clone()),
                        ..Default::default()
                    })
                    .await?;
                }
                cursor = Some(n);
            }
        }
    }

    /// Stages `bytes` with `create_upload_url`, PUTs them, and returns the
    /// `upload_id` (for `send_message.attachment_ids` or `send_file`).
    pub async fn upload_bytes(
        &self,
        conversation_id: &str,
        filename: &str,
        bytes: Vec<u8>,
        mime: Option<&str>,
    ) -> Result<String> {
        let t = self
            .create_upload_url(
                conversation_id,
                filename,
                bytes.len() as i64,
                crate::tools::CreateUploadUrlOpts {
                    mime: mime.map(str::to_string),
                },
            )
            .await?;
        let d = t.data();
        let url = d.get("upload_url").and_then(Value::as_str);
        let id = d.get("upload_id").and_then(Value::as_str);
        let (Some(url), Some(id)) = (url, id) else {
            return Err(Error::Protocol {
                code: None,
                message: "create_upload_url returned no upload_url/upload_id".into(),
            });
        };
        let headers: Vec<(String, String)> = d
            .get("headers")
            .and_then(Value::as_object)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| v.as_str().map(|v| (k.clone(), v.to_string())))
                    .collect()
            })
            .unwrap_or_default();
        self.put_bytes(url, bytes, &headers).await?;
        Ok(id.to_string())
    }

    /// Uploads a local file and sends it as its own message.
    pub async fn send_local_file(
        &self,
        conversation_id: &str,
        path: impl AsRef<std::path::Path>,
        caption: Option<&str>,
    ) -> Result<ToolResult> {
        let path = path.as_ref();
        let bytes = tokio::fs::read(path)
            .await
            .map_err(|e| Error::InvalidArgument(format!("cannot read file: {e}")))?;
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("file")
            .to_string();
        let id = self
            .upload_bytes(conversation_id, &name, bytes, None)
            .await?;
        self.send_file(
            conversation_id,
            id,
            SendFileOpts {
                caption: caption.map(str::to_string),
                ..Default::default()
            },
        )
        .await
    }
}
