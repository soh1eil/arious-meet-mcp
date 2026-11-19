package ariousmcp_test

// Live smoke test against the real server. Read-only calls ONLY: the handshake,
// prompts/list, whoami, start_here and context_list.
// Never add send_message / get_updates / read_messages / mark_read / ack_updates /
// context_checkpoint: they change state or mark the owner's messages as read.

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	ariousmcp "github.com/soh1eil/arious-meet-mcp/go"
)

func TestLiveReadOnly(t *testing.T) {
	if os.Getenv("ARIOUS_MCP_TOKEN") == "" {
		t.Skip("ARIOUS_MCP_TOKEN not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	c, err := ariousmcp.New()
	if err != nil {
		t.Fatal(err)
	}
	tools, err := c.ListTools(ctx)
	if err != nil || len(tools) < 100 {
		t.Fatalf("tools=%d err=%v", len(tools), err)
	}
	prompts, err := c.ListPrompts(ctx)
	if err != nil || len(prompts) < 2 {
		t.Fatalf("prompts=%d err=%v", len(prompts), err)
	}
	if r, err := c.Whoami(ctx, ariousmcp.WhoamiArgs{}); err != nil || r.Text == "" {
		t.Fatalf("whoami: %v", err)
	}
	r, err := c.StartHere(ctx, ariousmcp.StartHereArgs{})
	if err != nil {
		t.Fatalf("start_here: %v", err)
	}
	if s, err := ariousmcp.DecodeStartHere(r); err != nil || s.Identity.AgentID == "" || len(s.DoNow) == 0 || s.Text == "" {
		t.Fatalf("start_here decode: %+v %v", s, err)
	}
	if _, err := c.ContextList(ctx, ariousmcp.ContextListArgs{}); err != nil {
		// the owner may have switched Arious Context off
		var te *ariousmcp.ToolError
		if !errors.As(err, &te) || te.Result.Structured["contexts_enabled"] != false {
			t.Fatalf("context_list: %v", err)
		}
	}
}
