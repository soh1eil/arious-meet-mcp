package ariousmcp_test

// Live smoke test against the real server. Read-only tools ONLY:
// whoami, get_handbook, search_app_guide, list_organizations.
// Never add send_message / get_updates / read_messages / mark_read / ack_updates:
// they change state or mark the owner's messages as read.

import (
	"context"
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
	if r, err := c.Whoami(ctx, ariousmcp.WhoamiArgs{}); err != nil || r.Text == "" {
		t.Fatalf("whoami: %v", err)
	}
	if r, err := c.GetHandbook(ctx, ariousmcp.GetHandbookArgs{}); err != nil || len(r.Text) < 500 {
		t.Fatalf("handbook: %v", err)
	}
	if r, err := c.SearchAppGuide(ctx, ariousmcp.SearchAppGuideArgs{Query: "how do I create a group", Lang: "en"}); err != nil || r.Text == "" {
		t.Fatalf("guide: %v", err)
	}
	if _, err := c.ListOrganizations(ctx, ariousmcp.ListOrganizationsArgs{}); err != nil {
		t.Fatalf("orgs: %v", err)
	}
}
