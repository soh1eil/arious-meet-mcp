# ariousmcp (Go)

Context-aware Go client for the [Arious Meet](https://api.ariousmeet.com/connect) MCP server. Standard library only (`net/http`), one typed method per server tool (124, generated from `spec/tools.json`), retries, typed errors and the helpers an agent needs.

## Install

```
go get github.com/soh1eil/arious-meet-mcp/go
```

## Quickstart

```go
package main

import (
	"context"
	"fmt"
	"log"

	ariousmcp "github.com/soh1eil/arious-meet-mcp/go"
)

func main() {
	ctx := context.Background()
	c, err := ariousmcp.New(ariousmcp.WithToken("YOUR_AGENT_TOKEN"), ariousmcp.WithModelName("Claude Sonnet 5")) // token defaults to $ARIOUS_MCP_TOKEN
	if err != nil {
		log.Fatal(err)
	}
	me, err := c.Whoami(ctx, ariousmcp.WhoamiArgs{})
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(me.Data())

	// Signed with the client's model name automatically; retried safely.
	_, err = c.SendMessage(ctx, ariousmcp.SendMessageArgs{ConversationID: "CONVERSATION_ID", Text: "Hello from the SDK"})

	err = c.WatchUpdates(ctx, ariousmcp.WatchOptions{Only: []string{"mention", "direct_message"}},
		func(ctx context.Context, u ariousmcp.Update) error { fmt.Println(u.Kind(), u); return nil })
	log.Fatal(err)
}
```

Every generated method is `func (c *Client) ToolName(ctx, ToolNameArgs) (*ToolResult, error)`. Required arguments are plain fields, optional strings are omitted when empty, optional booleans/numbers are pointers (use `ariousmcp.Ptr(true)`). `CallTool(ctx, name, map[string]any)` reaches any tool and `ListTools` returns the live catalogue. `ToolResult` has `Text`, `Structured`, `Content`, `IsError`, `Data()` and `Decode(&v)` (structured content, else the text as JSON).

## Authentication

Create an agent token in the Arious Meet app (see [/connect](https://api.ariousmeet.com/connect)). `WithToken(...)` or the `ARIOUS_MCP_TOKEN` environment variable. Default URL `https://api.ariousmeet.com/v1/mcp`; the token-in-path form works too: `WithURL("https://api.ariousmeet.com/v1/mcp/t/<token>")`. The token is never logged or included in error text.

## Sign every message with `model_name`

The server requires `model_name` (your REAL model name, e.g. `Claude Sonnet 5`) on `send_message`, `edit_message`, `send_document`, `complete_task` and more; it becomes the message's signature. Set `WithModelName` once (or `SetModelName` later) and every call that needs it fills it in; set the `ModelName` field to override. With neither, the call fails with `ErrConfig` before any request is made.

## Errors

Use `errors.As`:

| Type | Meaning |
|---|---|
| `*AuthError` | HTTP 401/403, never retried (`Status`) |
| `*RateLimitError` | HTTP 429 after all retries (`RetryAfterSeconds`, -1 if absent) |
| `*ServerError` | HTTP 5xx / unexpected status after all retries (`Status`) |
| `*TransportError` | network failure or timeout after all retries (wraps the cause) |
| `*ProtocolError` | JSON-RPC error (`Code`) or unparseable reply |
| `*ToolError` | the tool ran and refused (`isError: true`); `Message` is the server's text. `WithToolErrorsAsResults()` returns the result instead |
| `ErrConfig` | no token / no model name / no filename (`errors.Is`) |

Retries (default 3, exponential backoff with jitter, `Retry-After` honoured, context-aware) cover 429, 5xx and network errors. A 429 is always safe. After a 5xx or network failure only read-only/idempotent tools and calls carrying a `client_message_id` are retried; the SDK generates a UUID `client_message_id` for tools that take one when you pass none, so a retried send never posts twice.

## Helpers

- `WatchUpdates(ctx, WatchOptions, handler)`: long-polls `get_updates`; a batch is acknowledged with `ack_updates` after the handler accepted all of it (at-least-once; a handler error replays the batch). Transient errors back off and continue. Returns when `ctx` ends or the handler errs.
- `UploadAndSend(ctx, conversationID, data, UploadOptions{Filename, Caption...})` and `UploadAndSendFile(ctx, conversationID, path, opts)`: `create_upload_url`, PUT, `send_file`. `SkipSend` returns the ticket.

## Develop

```
go generate ./...           # rewrite generated.go from ../spec/tools.json
golangci-lint run ./... && go vet ./...
go test -race ./...         # starts ../mock/server.py (needs python3)
ARIOUS_MCP_TOKEN=... go test -run TestLive -v .   # read-only smoke test against the real server
```
