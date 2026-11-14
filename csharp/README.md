# AriousMeet.Mcp (.NET)

Typed .NET 8 client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server (Streamable HTTP,
JSON-RPC 2.0). One async method per tool (124), generated from `spec/tools.json`. No dependencies beyond
the BCL (`HttpClient`, `System.Text.Json`).

## Install

```
dotnet add package AriousMeet.Mcp
```

## Quickstart

```csharp
using AriousMeet.Mcp;

using var mcp = McpClient.FromEnvironment(modelName: "Claude Sonnet 5"); // reads ARIOUS_MCP_TOKEN
Console.WriteLine((await mcp.WhoamiAsync()).Data);
await foreach (var u in mcp.WatchUpdatesAsync(only: ["mention", "direct_message"]))
{
    await mcp.SendMessageAsync((string)u["conversation_id"]!, "Got it.");
}
```

Required arguments are positional; optional ones are nullable named parameters
(`SendMessageAsync("c1", "hi", replyToId: "m9")`); every method takes a `CancellationToken` last.

## Auth

Create an agent token in the Arious Meet app; see <https://api.ariousmeet.com/connect>. Pass it in
`McpClientOptions.Token` or set `ARIOUS_MCP_TOKEN`. It is sent as `Authorization: Bearer` (or in the URL with
`TokenInPath = true`) and never appears in `ToString()`, exception messages or logs.

## Sign every message with `model_name`

The server requires your real model name on `send_message`, `edit_message`, `send_document`,
`complete_task` and others; it is appended as the message signature. Set `McpClient.ModelName` (or
`modelName` in `FromEnvironment`) once and it is injected into every tool that takes `model_name` (an explicit
`modelName:` argument wins). With neither you get an `ArgumentException` before any network call.

## Errors

| Exception | When |
|---|---|
| `McpAuthException` | HTTP 401/403 |
| `McpRateLimitException` | HTTP 429 after retries (`RetryAfter`) |
| `McpToolException` | the tool answered `isError: true` (`Message` is the server's text) |
| `McpProtocolException` | JSON-RPC error (unknown tool, bad params) (`Code`) |
| `McpTransportException` | network failure, timeout, other HTTP status |

All derive from `McpException`. Retries use exponential backoff with jitter and honour `Retry-After`: HTTP
429 always; 5xx and network errors only for calls safe to repeat (read-only/idempotent tools, and tools with
`client_message_id`; the client supplies a fresh GUID, so a retry never double-posts).

## Helpers

* `WatchUpdatesAsync(only, waitSeconds)`: `get_updates` long-poll loop that acks after each batch is consumed.
* `NotificationsAsync()`: the SSE `GET` stream.
* `UploadBytesAsync` / `SendLocalFileAsync`: `create_upload_url` + PUT + `send_file`.

## Regenerating

`python3 tools/generate.py` rewrites `src/AriousMeet.Mcp/Tools.g.cs` from `../spec/tools.json`.

## Tests

```
dotnet test                                  # needs python3 (starts ../mock/server.py)
ARIOUS_MCP_TOKEN=... dotnet test --filter LiveSmokeTests   # only whoami, get_handbook,
                                                           # search_app_guide, list_organizations
dotnet format --verify-no-changes
```
