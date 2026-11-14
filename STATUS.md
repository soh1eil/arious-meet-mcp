# Arious Meet MCP SDKs: status

Mock suite = full unit/integration suite against `mock/server.py` (json, sse, error 5xx, ratelimit 429 modes, auth, tool errors, idempotency, watch/ack, upload). Live smoke = `ARIOUS_MCP_TOKEN` against the real server calling only `list tools` handshake plus whoami, get_handbook, search_app_guide, list_organizations.

| Language | Package | Generator | Mock suite | Live smoke | Lint / format | Notes |
|---|---|---|---|---|---|---|
| Python | `arious-meet-mcp` (pypi, not published) | `python3 tools/generate.py` | 22 passed (sync + async) | pass | ruff check, ruff format, mypy --strict clean | httpx; sync `Client` and `AsyncClient`; py>=3.9 |
| TypeScript | `@arious-meet/mcp` (npm, not published) | `npm run generate` | 12 passed, 1 live (skipped without token) | pass | biome check clean, tsc strict | ESM, fetch only (Node 18+, Deno, Bun); zero runtime deps |
| Go | `github.com/ariousmeet/mcp-go` (module, not published) | `go generate ./...` | all passed with -race | pass | golangci-lint 0 issues, go vet clean | stdlib only; context-aware; Go 1.21+ |
| Java | `com.ariousmeet:arious-meet-mcp` (maven, not published) | `python3 tools/generate.py` | 17 passed (JUnit 5) | pass | `-Xlint:all -Werror`, spotless google-java-format clean | Java 17, `java.net.http` + Jackson; blocking API; optional args via trailing `Map` overload |
| Dart | `arious_meet_mcp` (pub, not published) | `python3 tool/generate.py` | 26 passed | pass | dart analyze 0 issues, dart format clean, `pub publish --dry-run` 0 warnings | `package:http`; extension methods with named params |
| Rust | `arious-meet-mcp` (crates.io, not published) | `python3 tools/generate.py` | 16 passed (15 integration + 1 doc) | pass | cargo fmt --check, clippy `-D warnings` clean, `cargo package` ok | reqwest (rustls) + serde + tokio; required args positional, optional in generated `<Tool>Opts` structs |
| C# | `AriousMeet.Mcp` (nuget, not published) | `python3 tools/generate.py` | 18 passed (xunit) | pass | `dotnet format --verify-no-changes`, warnings-as-errors, `dotnet pack` ok | .NET 8, BCL only; nullable named params + `CancellationToken`; `IAsyncEnumerable` watch/notifications |

Shared mock: `mock/server.py` (see `mock/README.md`).
