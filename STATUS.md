# Arious Meet MCP SDKs: status

Mock suite = full unit/integration suite against `mock/server.py` (json, sse, error 5xx, ratelimit 429 modes, auth, tool errors, idempotency, watch/ack, upload, Arious Context incl. conflict and redaction, start_here, prompts, platform updates and the context reminder). Live smoke = `ARIOUS_MCP_TOKEN` against the real server calling only the handshake, `prompts/list`, `whoami`, `start_here` and `context_list` (all read-only; no message is marked read, no checkpoint written).

| Language | Package | Generator | Mock suite | Live smoke | Lint / format | Notes |
|---|---|---|---|---|---|---|
| Python | `arious-meet-mcp` 0.3.0 (pypi, not published) | `python3 tools/generate.py` | 42 passed (sync + async) | pass | ruff check, ruff format, mypy --strict clean | httpx; sync `Client` and `AsyncClient`; py>=3.9 |
| TypeScript | `@arious-meet/mcp` 0.3.0 (npm, not published) | `npm run generate` | 29 passed, 1 live (skipped without token) | pass | biome check clean, tsc strict | ESM, fetch only (Node 18+, Deno, Bun); zero runtime deps |
| Go | `github.com/soh1eil/arious-meet-mcp/go` 0.3.0 (module, not published) | `go generate ./...` | 27 passed with -race (live skipped without token) | pass | golangci-lint 0 issues, go vet clean | stdlib only; context-aware; Go 1.21+ |
| Java | `com.ariousmeet:arious-meet-mcp` 0.3.0 (maven, not published) | `python3 tools/generate.py` | 34 passed (JUnit 5), 1 live | pass | `-Xlint:all -Werror`, spotless google-java-format clean | Java 17, `java.net.http` + Jackson; blocking API; optional args via trailing `Map` overload |
| Dart | `arious_meet_mcp` 0.3.0 (pub, not published) | `python3 tool/generate.py` | 43 passed, 1 live (skipped without token) | pass | dart analyze 0 issues, dart format clean, `pub publish --dry-run` 0 warnings once committed | `package:http`; extension methods with named params |
| Rust | `arious-meet-mcp` 0.3.0 (crates.io, not published) | `python3 tools/generate.py` | 31 passed (30 integration + 1 doc), 1 live | pass | cargo fmt --check, clippy `-D warnings` clean, `cargo package` ok | reqwest (rustls) + serde + tokio; required args positional, optional in generated `<Tool>Opts` structs |
| C# | `AriousMeet.Mcp` 0.3.0 (nuget, not published) | `python3 tools/generate.py` | 34 passed (xunit), 1 live | pass | `dotnet format --verify-no-changes`, warnings-as-errors, `dotnet pack` ok | .NET 8, BCL only; nullable named params + `CancellationToken`; `IAsyncEnumerable` watch/notifications |

All seven SDKs are at **0.3.0** and cover the 143-tool catalogue (was 127 at 0.2.0). Added since 0.2.0, all taken from the live server's `tools/list` and `prompts/list` on 2026-11-19:

- **Arious Context tools**: `context_list`, `context_search`, `context_get`, `context_resume`, `context_create`, `context_checkpoint`, `context_set_status`, all with an optional `organization_id` (`context_create` also `classification`, `context_resume` also `conversation_id`), and `start_here`.
- **Office tools found by diffing** (not in the brief, but live): `list_cartable`, `get_letter`, `draft_letter`, `suggest_referral`, `summarize_letter`, `search_archive`, `extract_letter_scan`, `get_office_report`. They are generated like every other tool; there are no typed results for them.
- **Changed tools**: `ack_updates` now takes `update_ids` and `cursor` is optional (a source-level change in the Python, Java, Rust and C# wrappers, see each CHANGELOG); `get_handbook` gained the sections `office` and `context`; `send_widget` has a new description.
- **Prompts**: `prompts/list` and `prompts/get` (`start`, `resume`) as `list_prompts` / `get_prompt` (`listPrompts` / `getPrompt`, `ListPrompts` / `GetPrompt`, `ListPromptsAsync` / `GetPromptAsync`) in every SDK.
- **Typed results**: `context_resume` (brief + structured), `context_checkpoint` (version, redacted list, conflict + latest) and `start_here`, plus `ToolResult` access to the `context_reminder` field and to `platform_update` items of `get_updates`.
- **Conflict**: `ContextConflict` error (a subclass of the tool error in every language; Rust has `Error::ContextConflict`) when a checkpoint answers `conflict: true`; the raw result form is available with `raise_on_tool_error=False` / `callToolRaw` / `WithToolErrorsAsResults` / `throwOnError: false`.
- **Examples** "resume where another agent left off": `python/examples/resume_context.py`, `typescript/examples/resume-context.mjs`, `go/examples/resume/main.go`, `java/examples/ResumeContext.java`, `dart/example/resume_context.dart`, `rust/examples/resume_context.rs`, `csharp/examples/ResumeContext.cs.txt`; every README has an "Arious Context" section.

The live server's `tools/list` was compared with `spec/tools.json` on 2026-11-19 (names, input schemas, annotations): `spec/tools.json` is that listing, 143 tools; the 127 tools of 0.2.0 are unchanged except for the three changed ones above. `initialize` now advertises the `prompts` capability.

How the numbers above were produced: each SDK's lint/format commands and its mock suite were run on this host on 2026-11-19 (Python in a throwaway venv with ruff and mypy; TypeScript after `npm ci`; .NET 8 SDK installed outside the default PATH). The live smoke was run once per SDK with the agent token from the environment; every call was read-only. The Java and C# live tests, like the other live tests, skip (or return) without `ARIOUS_MCP_TOKEN`, so the mock suite counts above exclude them.

Shared mock: `mock/server.py` (see `mock/README.md`).
