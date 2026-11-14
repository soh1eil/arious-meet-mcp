use std::time::Duration;

use serde_json::Value;

/// Every error this crate returns.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// HTTP 401/403: the token is missing, wrong, expired or revoked.
    #[error("authentication failed (HTTP {status}): {message}")]
    Auth { status: u16, message: String },

    /// HTTP 429 after retries ran out.
    #[error("rate limited: {message}")]
    RateLimit {
        message: String,
        retry_after: Option<Duration>,
    },

    /// The tool ran and answered `isError: true`.
    #[error("tool {tool} failed: {message}")]
    Tool {
        tool: String,
        message: String,
        result: Value,
    },

    /// A JSON-RPC error (unknown method/tool, invalid params, ...).
    #[error("protocol error {code:?}: {message}")]
    Protocol { code: Option<i64>, message: String },

    /// Network failure, timeout, or an unexpected HTTP status.
    #[error("transport error: {message}")]
    Transport {
        message: String,
        status: Option<u16>,
    },

    /// The caller passed something the SDK can reject before the network.
    #[error("invalid argument: {0}")]
    InvalidArgument(String),
}

/// `Result` alias.
pub type Result<T> = std::result::Result<T, Error>;
