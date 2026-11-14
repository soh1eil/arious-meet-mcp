//! Typed async client for the Arious Meet MCP server.
//!
//! ```no_run
//! # async fn demo() -> arious_meet_mcp::Result<()> {
//! use arious_meet_mcp::Client;
//! let mcp = Client::from_env(Some("Claude Sonnet 5"))?; // reads ARIOUS_MCP_TOKEN
//! println!("{}", mcp.whoami().await?.data());
//! # Ok(()) }
//! ```
#![forbid(unsafe_code)]

mod client;
mod error;
mod helpers;
mod sse;
mod tools;
mod types;

pub use client::{
    Client, ClientBuilder, ToolResult, ToolTraits, DEFAULT_BASE_URL, PROTOCOL_VERSION,
};
pub use error::{Error, Result};
pub use helpers::WatchOptions;
pub use sse::{parse_sse_data, SseParser};
pub use tools::*;
pub use types::{ChatAction, Gif, SearchGifsResult, SendGifResult};
