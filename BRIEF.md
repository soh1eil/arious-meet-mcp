# Arious Meet MCP SDKs — shared brief

Owner (Soheil): «میخوام با همه زبان‌های معروف ابزارهای MCP رو بساز که اگر خواستند ایجنت‌های کدنویسی بردارند و استفاده بکنند، که مطمئن بشیم بی‌خطاست»
= client SDKs, in the popular languages, for the Arious Meet MCP server, so any coding agent / developer can connect an agent reliably and error-free.

Repo: <repo> (standalone git repo, NOT the product repo; rule 4 "only Go and Dart" binds the product only). One folder per language: python/, typescript/, go/, java/, dart/, rust/, csharp/. Commit with exact `git add`, no Co-Authored-By/Claude lines, do not push anywhere.

Server facts:
- Endpoint: https://api.ariousmeet.com/v1/mcp — MCP over Streamable HTTP (JSON-RPC 2.0 POST; responses may be `application/json` or an SSE stream with `data:` lines). Auth: `Authorization: Bearer <agent token>`. Also a token-in-path form /v1/mcp/t/{token} exists (see the server's transport code for the exact protocol: initialize, tools/list, tools/call, notifications, session id header if any, SSE GET for server→client events, error shapes, rate limits).
- Human-facing setup guide: GET https://api.ariousmeet.com/connect (server code internal/transport/connect*.go) — match its terminology.
- Tool catalogue snapshot (124 tools, with inputSchema + annotations): <repo>/spec/tools.json. Each SDK must GENERATE its typed tool wrappers from this file with a generator script inside the repo (so regenerating after server changes is one command), not hand-write 124 functions.

Every SDK must have:
1. Low-level client: initialize handshake, tools/list, tools/call returning structured content; SSE and plain-JSON responses both handled; timeouts; retries with backoff on 429/5xx/network errors (idempotent-safe: honour client_message_id where tools accept it); typed errors (auth, rate-limit, tool error with message, protocol error).
2. Generated typed wrappers for all tools (argument types from inputSchema; required vs optional), docstrings from descriptions.
3. Helpers: watch for updates (get_updates long-poll loop with ack), send_message with automatic model_name, upload a file (create_upload_url + PUT + send_file).
4. README (English) with install, 10-line quickstart, auth, error handling, the "sign every message with model_name" rule, links to /connect.
5. Tests: (a) a full unit/integration suite against a local MOCK MCP server (write one shared mock in Python at <repo>/mock/ that implements initialize/tools/list/tools/call for a handful of tools, SSE + JSON modes, error and 429 modes — reuse it from every language's tests); (b) a LIVE smoke test against the real server that calls ONLY these read-only, side-effect-free tools: `whoami`, `get_handbook`, `search_app_guide`, `list_organizations`. NEVER call any other tool on the live server — in particular never send_message, get_updates, read_messages, mark_read, ack_updates (they change state or mark the owner's messages as read). Live token: read from env `ARIOUS_MCP_TOKEN`; for running the smoke test locally use `ARIOUS_MCP_TOKEN` from your own agent token. Never print, log, commit or write the token anywhere.
6. Lint/format clean for the language; package metadata ready for its registry (pypi/npm/go module/maven/pub/crates/nuget) but DO NOT publish.

Host shares CPU with production: prefix builds/tests with `nice -n 10 ionice -c3`. You may `apt-get install` toolchains (owner allows installs on servers) — e.g. rustc/cargo, dotnet-sdk — prefer distro packages. Never pkill/killall, never prune Docker.

Final report: per language — what's built, test results (mock suite + live smoke), anything missing; plus a single summary table at <repo>/STATUS.md.
