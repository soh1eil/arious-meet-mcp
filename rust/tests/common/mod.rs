#![allow(dead_code)]
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

use arious_meet_mcp::Client;
use serde_json::{json, Value};

/// Starts the shared Python mock (../mock/server.py) on a free port.
pub struct Mock {
    child: Child,
    pub url: String,
    pub origin: String,
}

impl Mock {
    pub fn start(mode: &str) -> Mock {
        let script = format!("{}/../mock/server.py", env!("CARGO_MANIFEST_DIR"));
        let mut child = Command::new("python3")
            .args([&script, "--port", "0", "--mode", mode, "--fail-count", "2"])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("python3 must be installed to run the mock");
        let out = child.stdout.take().unwrap();
        let mut line = String::new();
        BufReader::new(out).read_line(&mut line).unwrap();
        let url = line
            .trim()
            .strip_prefix("LISTENING ")
            .expect("mock banner")
            .to_string();
        let origin = url.replace("/v1/mcp", "");
        Mock { child, url, origin }
    }

    pub async fn log(&self) -> Vec<Value> {
        let v: Value = reqwest::get(format!("{}/__mock/log", self.origin))
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        v["log"].as_array().cloned().unwrap_or_default()
    }

    pub async fn actions(&self, conversation: &str) -> Vec<String> {
        let v: Value = reqwest::get(format!("{}/__mock/log", self.origin))
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        v["actions"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .filter(|a| a["conversation_id"] == conversation)
            .map(|a| a["action"].as_str().unwrap().to_string())
            .collect()
    }

    pub async fn push(&self, token: &str, items: Value) {
        reqwest::Client::new()
            .post(format!("{}/__mock/push", self.origin))
            .body(json!({"token": token, "items": items}).to_string())
            .send()
            .await
            .unwrap();
    }

    pub fn client(&self) -> Client {
        self.client_with(&unique_token(), Some("Test Model"))
    }

    pub fn client_with(&self, token: &str, model: Option<&str>) -> Client {
        let mut b = Client::builder()
            .token(token)
            .base_url(self.url.clone())
            .backoff_base(std::time::Duration::from_millis(5));
        if let Some(m) = model {
            b = b.model_name(m);
        }
        b.build().unwrap()
    }
}

impl Drop for Mock {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

static N: AtomicU64 = AtomicU64::new(0);
pub fn unique_token() -> String {
    format!(
        "test-rust-{}-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_micros(),
        N.fetch_add(1, Ordering::SeqCst)
    )
}
