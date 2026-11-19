package ariousmcp_test

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"

	ariousmcp "github.com/soh1eil/arious-meet-mcp/go"
)

func control(t *testing.T, path, body string) {
	t.Helper()
	resp, err := http.Post(strings.Replace(mockURL, "/v1/mcp", path, 1), "application/json", bytes.NewBufferString(body))
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
}

func newContext(t *testing.T, c *ariousmcp.Client, title, goal string) string {
	t.Helper()
	res, err := c.ContextCreate(context.Background(), ariousmcp.ContextCreateArgs{Title: title, Goal: goal})
	if err != nil {
		t.Fatal(err)
	}
	return res.Structured["context"].(map[string]any)["id"].(string)
}

func TestResumeWhereAnotherAgentLeftOff(t *testing.T) {
	for _, mode := range []string{"json", "sse"} {
		t.Run(mode, func(t *testing.T) {
			ctx := context.Background()
			token := tok()
			writer := mk(t, token, mode, ariousmcp.WithModelName("Agent A"))
			cid := newContext(t, writer, "Ship 0.3", "Release the SDK")
			r, err := writer.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{
				ContextID: cid, BaseVersion: 1, CurrentStep: "Writing tests",
				Append: &ariousmcp.ContextCheckpointArgsAppend{DoneSteps: []string{"Spec read"}, NextSteps: []string{"Run the suite"}},
			})
			if err != nil {
				t.Fatal(err)
			}
			first, err := ariousmcp.DecodeCheckpoint(r)
			if err != nil || first.Version != 2 || first.Conflict || len(first.Redacted) != 0 {
				t.Fatalf("first=%+v err=%v", first, err)
			}

			reader := mk(t, token, mode, ariousmcp.WithModelName("Agent B"))
			rr, err := reader.ContextResume(ctx, ariousmcp.ContextResumeArgs{}) // newest active context
			if err != nil {
				t.Fatal(err)
			}
			resume, err := ariousmcp.DecodeContextResume(rr)
			if err != nil || resume.ContextID != cid || resume.Version != 2 || !resume.CanWrite || resume.Scope != "personal" {
				t.Fatalf("resume=%+v err=%v", resume, err)
			}
			if !strings.Contains(resume.Brief, "Where we are now: Writing tests") || !strings.Contains(resume.Brief, "Next step: Run the suite") {
				t.Fatalf("brief=%q", resume.Brief)
			}
			nr, err := reader.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{
				ContextID: cid, BaseVersion: resume.Version,
				Append: &ariousmcp.ContextCheckpointArgsAppend{DoneSteps: []string{"Suite green"}},
			})
			if err != nil {
				t.Fatal(err)
			}
			if next, _ := ariousmcp.DecodeCheckpoint(nr); next.Version != 3 {
				t.Fatalf("next=%+v", next)
			}
			g, err := reader.ContextGet(ctx, ariousmcp.ContextGetArgs{ContextID: cid, History: ariousmcp.Ptr(int64(2))})
			if err != nil {
				t.Fatal(err)
			}
			v := g.Structured["version"].(map[string]any)
			if v["author"].(map[string]any)["model"] != "Agent B" || len(v["done_steps"].([]any)) != 2 || len(g.Structured["history"].([]any)) != 2 {
				t.Fatalf("get=%v", g.Structured)
			}
		})
	}
}

func TestCheckpointRedactsSecrets(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	cid := newContext(t, c, "T", "g")
	r, err := c.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{
		ContextID: cid, BaseVersion: 1, Notes: "use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here",
	})
	if err != nil {
		t.Fatal(err)
	}
	res, _ := ariousmcp.DecodeCheckpoint(r)
	got := map[string]int64{}
	for _, x := range res.Redacted {
		got[x.Field+"/"+x.Kind] = x.Count
	}
	if len(got) != 2 || got["notes/api_key"] != 1 || got["notes/secret_value"] != 1 {
		t.Fatalf("redacted=%v", got)
	}
	g, _ := c.ContextGet(ctx, ariousmcp.ContextGetArgs{ContextID: cid})
	notes := g.Structured["version"].(map[string]any)["notes"].(string)
	if strings.Contains(notes, "hunter2") || !strings.Contains(notes, "[REDACTED:api_key]") {
		t.Fatalf("notes=%q", notes)
	}
}

func TestConflictIsTypedError(t *testing.T) {
	ctx := context.Background()
	token := tok()
	c := mk(t, token, "json")
	cid := newContext(t, c, "T", "g")
	control(t, "/__mock/context_write", `{"token":"`+token+`","context_id":"`+cid+`","current_step":"elsewhere","model":"Other"}`)
	_, err := c.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{ContextID: cid, BaseVersion: 1, CurrentStep: "mine"})
	ce, ok := ariousmcp.IsContextConflict(err)
	if !ok || ce.BaseVersion != 1 || ce.LatestVersion != 2 || ce.Latest == nil ||
		ce.Latest.CurrentStep != "elsewhere" || ce.Latest.Author.Model != "Other" {
		t.Fatalf("err=%v ce=%+v", err, ce)
	}
	var te *ariousmcp.ToolError // old handlers keep working
	if !errors.As(err, &te) || te.Result == nil {
		t.Fatalf("not a ToolError: %v", err)
	}
	r, err := c.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{ContextID: cid, BaseVersion: ce.LatestVersion, CurrentStep: "mine"})
	if err != nil {
		t.Fatal(err)
	}
	if ok, _ := ariousmcp.DecodeCheckpoint(r); ok.Version != 3 {
		t.Fatalf("retry=%+v", ok)
	}
}

func TestConflictAsResult(t *testing.T) {
	ctx := context.Background()
	token := tok()
	c := mk(t, token, "json", ariousmcp.WithToolErrorsAsResults())
	cid := newContext(t, c, "T", "g")
	control(t, "/__mock/context_write", `{"token":"`+token+`","context_id":"`+cid+`"}`)
	r, err := c.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{ContextID: cid, BaseVersion: 1})
	if err != nil || !r.IsError {
		t.Fatalf("r=%+v err=%v", r, err)
	}
	res, err := ariousmcp.DecodeCheckpoint(r)
	if err != nil || !res.Conflict || res.BaseVersion != 1 || res.LatestVersion != 2 || res.Latest == nil || res.Latest.Version != 2 {
		t.Fatalf("res=%+v err=%v", res, err)
	}
}

func TestOtherToolErrorsStayPlain(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	_, err := c.ContextGet(ctx, ariousmcp.ContextGetArgs{ContextID: "nope"})
	var te *ariousmcp.ToolError
	if _, isConflict := ariousmcp.IsContextConflict(err); isConflict || !errors.As(err, &te) || !strings.Contains(te.Message, "not found") {
		t.Fatalf("err=%v", err)
	}
	if _, err := c.ContextResume(ctx, ariousmcp.ContextResumeArgs{}); err == nil || !strings.Contains(err.Error(), "no active context") {
		t.Fatalf("err=%v", err)
	}
}

func TestListSearchStatus(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	a := newContext(t, c, "Alpha plan", "first goal")
	b := newContext(t, c, "Beta plan", "second goal")
	ids := func(r *ariousmcp.ToolResult) []string {
		var out []string
		for _, x := range r.Structured["contexts"].([]any) {
			out = append(out, x.(map[string]any)["id"].(string))
		}
		return out
	}
	all, _ := c.ContextList(ctx, ariousmcp.ContextListArgs{})
	if len(ids(all)) != 2 {
		t.Fatalf("all=%v", ids(all))
	}
	if _, err := c.ContextSetStatus(ctx, ariousmcp.ContextSetStatusArgs{ContextID: a, Status: "paused"}); err != nil {
		t.Fatal(err)
	}
	paused, _ := c.ContextList(ctx, ariousmcp.ContextListArgs{Status: "paused"})
	if got := ids(paused); len(got) != 1 || got[0] != a {
		t.Fatalf("paused=%v", got)
	}
	hit, _ := c.ContextSearch(ctx, ariousmcp.ContextSearchArgs{Query: "second"})
	if got := ids(hit); len(got) != 1 || got[0] != b {
		t.Fatalf("search=%v", got)
	}
	if _, err := c.ContextSetStatus(ctx, ariousmcp.ContextSetStatusArgs{ContextID: a, Status: "archived"}); err == nil {
		t.Fatal("archived must be refused")
	}
}

func TestContextOffIsToolErrorWithReason(t *testing.T) {
	ctx := context.Background()
	token := tok()
	c := mk(t, token, "json")
	control(t, "/__mock/contexts", `{"token":"`+token+`","enabled":false}`)
	_, err := c.ContextList(ctx, ariousmcp.ContextListArgs{})
	var te *ariousmcp.ToolError
	if !errors.As(err, &te) || te.Result.Structured["contexts_enabled"] != false || te.Result.Structured["reason"] != "turned_off_by_owner" {
		t.Fatalf("err=%v", err)
	}
	s, _ := c.StartHere(ctx, ariousmcp.StartHereArgs{})
	if sh, _ := ariousmcp.DecodeStartHere(s); sh.LastContext.Enabled {
		t.Fatal("start_here must say contexts are off")
	}
	control(t, "/__mock/contexts", `{"token":"`+token+`","enabled":true}`)
	if _, err := c.ContextList(ctx, ariousmcp.ContextListArgs{}); err != nil {
		t.Fatal(err)
	}
}

func TestOrganizationScopeAndClassification(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	personal := newContext(t, c, "Mine", "g")
	cr, err := c.ContextCreate(ctx, ariousmcp.ContextCreateArgs{Title: "Board pack", Goal: "g", OrganizationID: "org-1", Classification: "confidential"})
	if err != nil {
		t.Fatal(err)
	}
	oc := cr.Structured["context"].(map[string]any)
	if oc["scope"] != "organization" || oc["classification"] != "confidential" {
		t.Fatalf("ctx=%v", oc)
	}
	pl, _ := c.ContextList(ctx, ariousmcp.ContextListArgs{})
	if l := pl.Structured["contexts"].([]any); len(l) != 1 || l[0].(map[string]any)["id"] != personal {
		t.Fatalf("personal list=%v", l)
	}
	ol, _ := c.ContextList(ctx, ariousmcp.ContextListArgs{OrganizationID: "org-1"})
	if ol.Structured["scope"] != "organization" || len(ol.Structured["contexts"].([]any)) != 1 {
		t.Fatalf("org list=%v", ol.Structured)
	}
	rr, err := c.ContextResume(ctx, ariousmcp.ContextResumeArgs{ContextID: oc["id"].(string), OrganizationID: "org-1", ConversationID: "conv-1"})
	if err != nil {
		t.Fatal(err)
	}
	res, _ := ariousmcp.DecodeContextResume(rr)
	if res.Scope != "organization" || res.OrganizationID != "org-1" || res.Classification != "confidential" {
		t.Fatalf("res=%+v", res)
	}
	if _, err := c.ContextCreate(ctx, ariousmcp.ContextCreateArgs{Title: "S", OrganizationID: "org-1", Classification: "secret"}); err == nil || !strings.Contains(err.Error(), "clearance") {
		t.Fatalf("err=%v", err)
	}
	if _, err := c.ContextList(ctx, ariousmcp.ContextListArgs{OrganizationID: "org-9"}); err == nil || !strings.Contains(err.Error(), "organization not found") {
		t.Fatalf("err=%v", err)
	}
}

func TestStartHereTypedAndAckByID(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	cid := newContext(t, c, "Resume me", "goal")
	r, err := c.StartHere(ctx, ariousmcp.StartHereArgs{})
	if err != nil {
		t.Fatal(err)
	}
	s, err := ariousmcp.DecodeStartHere(r)
	if err != nil || s.Identity.Name != "Mock Agent" || !s.LastContext.Enabled || s.LastContext.ContextID != cid ||
		!strings.Contains(s.LastContext.Brief, "Resume me") || s.PlatformUpdates.UnreadCount != 2 ||
		len(s.Conversations) != 1 || s.Conversations[0].ID != "conv-1" || len(s.HouseRules) == 0 || len(s.DoNow) == 0 ||
		!strings.HasPrefix(s.Text, "START HERE") {
		t.Fatalf("s=%+v err=%v", s, err)
	}
	ids := s.ImportantUpdateIDs()
	if len(ids) != 1 || ids[0] != "upd-context" {
		t.Fatalf("ids=%v", ids)
	}
	if _, err := c.AckUpdates(ctx, ariousmcp.AckUpdatesArgs{UpdateIDs: ids}); err != nil {
		t.Fatal(err)
	}
	r2, _ := c.StartHere(ctx, ariousmcp.StartHereArgs{})
	if s2, _ := ariousmcp.DecodeStartHere(r2); len(s2.ImportantUpdateIDs()) != 0 {
		t.Fatalf("still important: %v", s2.ImportantUpdateIDs())
	}
	if _, err := c.AckUpdates(ctx, ariousmcp.AckUpdatesArgs{}); err == nil {
		t.Fatal("ack with neither cursor nor update_ids must be refused")
	}
}

func TestPromptsListAndGet(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	prompts, err := c.ListPrompts(ctx)
	if err != nil || len(prompts) != 2 {
		t.Fatalf("prompts=%+v err=%v", prompts, err)
	}
	names := map[string]ariousmcp.Prompt{}
	for _, p := range prompts {
		names[p.Name] = p
	}
	resume, ok := names["resume"]
	if !ok || len(names["start"].Arguments) != 0 || len(resume.Arguments) != 2 ||
		resume.Arguments[0].Name != "context_id" || resume.Arguments[0].Required {
		t.Fatalf("names=%+v", names)
	}
	cid := newContext(t, c, "Prompted", "g")
	res, err := c.GetPrompt(ctx, "resume", map[string]string{"context_id": cid})
	if err != nil || len(res.Messages) != 1 || res.Messages[0].Role != "user" || !strings.Contains(res.Text(), "Title: Prompted") {
		t.Fatalf("res=%+v err=%v", res, err)
	}
	if st, err := c.GetPrompt(ctx, "start", nil); err != nil || !strings.Contains(st.Text(), "START HERE") {
		t.Fatalf("start=%+v err=%v", st, err)
	}
	_, err = c.GetPrompt(ctx, "nope", nil)
	var pe *ariousmcp.ProtocolError
	if !errors.As(err, &pe) || pe.Code != -32602 {
		t.Fatalf("err=%v", err)
	}
}

func TestContextReminderAndPlatformUpdateItems(t *testing.T) {
	ctx := context.Background()
	token := tok()
	c := mk(t, token, "json")
	control(t, "/__mock/push", `{"token":"`+token+`","items":[
		{"kind":"message","conversation_id":"c1","message_id":"m1","text":"hi"},
		{"kind":"platform_update","id":"upd-x","title":"New","importance":"important"}]}`)
	res, err := c.GetUpdates(ctx, ariousmcp.GetUpdatesArgs{})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(res.ContextReminder(), "context_checkpoint") {
		t.Fatalf("reminder=%q", res.ContextReminder())
	}
	if pu := res.PlatformUpdates(); len(pu) != 1 || pu[0].ID != "upd-x" || !pu[0].Important() {
		t.Fatalf("pu=%+v", pu)
	}
	rm, _ := c.ReadMessages(ctx, ariousmcp.ReadMessagesArgs{ConversationID: "c1"})
	gm, _ := c.GetMessage(ctx, ariousmcp.GetMessageArgs{ConversationID: "c1", MessageID: "m1"})
	empty, _ := c.ReadMessages(ctx, ariousmcp.ReadMessagesArgs{ConversationID: "empty"})
	if rm.ContextReminder() == "" || gm.ContextReminder() == "" || empty.ContextReminder() != "" {
		t.Fatal("reminder on read_messages/get_message wrong")
	}
	control(t, "/__mock/contexts", `{"token":"`+token+`","enabled":false}`)
	off, _ := c.GetUpdates(ctx, ariousmcp.GetUpdatesArgs{})
	if off.ContextReminder() != "" {
		t.Fatal("reminder must disappear when contexts are off")
	}
}
