# Arious Meet MCP SDKs: status

Mock suite = full unit/integration suite against `mock/server.py` (json, sse, error 5xx, ratelimit 429 modes, auth, tool errors, idempotency, watch/ack, upload). Live smoke = `ARIOUS_MCP_TOKEN` against the real server calling only `list tools` handshake plus whoami, get_handbook, search_app_guide, list_organizations.

| Language | Package | Generator | Mock suite | Live smoke | Lint / format | Notes |
|---|---|---|---|---|---|---|
| Python | `arious-meet-mcp` 0.2.0 (pypi, not published) | `python3 tools/generate.py` | 29 passed (sync + async) | pass | ruff check, ruff format, mypy --strict clean | httpx; sync `Client` and `AsyncClient`; py>=3.9 |
| TypeScript | `@arious-meet/mcp` 0.2.0 (npm, not published) | `npm run generate` | 17 passed, 1 live (skipped without token) | pass | biome check clean, tsc strict | ESM, fetch only (Node 18+, Deno, Bun); zero runtime deps |
| Go | `github.com/soh1eil/arious-meet-mcp/go` 0.2.0 (module, not published) | `go generate ./...` | 16 passed with -race (live skipped without token) | pass | golangci-lint 0 issues, go vet clean | stdlib only; context-aware; Go 1.21+ |
| Java | `com.ariousmeet:arious-meet-mcp` 0.2.0 (maven, not published) | `python3 tools/generate.py` | 22 passed (JUnit 5), 1 live | pass | `-Xlint:all -Werror`, spotless google-java-format clean | Java 17, `java.net.http` + Jackson; blocking API; optional args via trailing `Map` overload |
| Dart | `arious_meet_mcp` 0.2.0 (pub, not published) | `python3 tool/generate.py` | 31 passed | pass | dart analyze 0 issues, dart format clean, `pub publish --dry-run` 0 warnings | `package:http`; extension methods with named params |
| Rust | `arious-meet-mcp` 0.2.0 (crates.io, not published) | `python3 tools/generate.py` | 20 passed (19 integration + 1 doc), 1 live | pass | cargo fmt --check, clippy `-D warnings` clean, `cargo package` ok | reqwest (rustls) + serde + tokio; required args positional, optional in generated `<Tool>Opts` structs |
| C# | `AriousMeet.Mcp` 0.2.0 (nuget, not published) | `python3 tools/generate.py` | 23 passed (xunit), 1 live | pass | `dotnet format --verify-no-changes`, warnings-as-errors, `dotnet pack` ok | .NET 8, BCL only; nullable named params + `CancellationToken`; `IAsyncEnumerable` watch/notifications |

All seven SDKs are at **0.2.0** and cover the 127-tool catalogue, including the 2026-11-14 additions: `send_chat_action`, `send_typing` with the optional `action`, `search_gifs` and `send_gif`. Each has a `ChatAction` enum and typed GIF results (Python `SearchGifsResult.from_result`, TypeScript generic `ToolResult<SearchGifsResult>`, Go `DecodeSearchGifs`, Java/C#/Dart `SearchGifsResult.from/From/fromResult`, Rust `ToolResult::decode`). The live server's `tools/list` was compared with `spec/tools.json`: all 127 names, input schemas and annotations are identical.

Shared mock: `mock/server.py` (see `mock/README.md`).
