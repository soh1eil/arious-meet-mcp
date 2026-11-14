package ariousmcp_test

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	ariousmcp "github.com/soh1eil/arious-meet-mcp/go"
)

var mockURL string

func TestMain(m *testing.M) {
	cmd := exec.Command("python3", filepath.Join("..", "mock", "server.py"), "--port", "0")
	out, err := cmd.StdoutPipe()
	if err != nil {
		panic(err)
	}
	if err := cmd.Start(); err != nil {
		panic(err)
	}
	line, _ := bufio.NewReader(out).ReadString('\n')
	mockURL = strings.TrimSpace(strings.TrimPrefix(line, "LISTENING "))
	code := m.Run()
	_ = cmd.Process.Kill()
	os.Exit(code)
}

type modeTransport struct{ mode string }

func (t modeTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	r = r.Clone(r.Context())
	r.Header.Set("X-Mock-Mode", t.mode)
	return http.DefaultTransport.RoundTrip(r)
}

func tok() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return "test-" + hex.EncodeToString(b)
}

func mk(t *testing.T, token, mode string, extra ...ariousmcp.Option) *ariousmcp.Client {
	t.Helper()
	opts := []ariousmcp.Option{
		ariousmcp.WithToken(token), ariousmcp.WithURL(mockURL), ariousmcp.WithModelName("Test Model"),
		ariousmcp.WithBackoff(5 * time.Millisecond),
		ariousmcp.WithHTTPClient(&http.Client{Transport: modeTransport{mode}, Timeout: 10 * time.Second}),
	}
	c, err := ariousmcp.New(append(opts, extra...)...)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func push(t *testing.T, token string, texts ...string) {
	t.Helper()
	var items []string
	for _, x := range texts {
		items = append(items, `{"kind":"mention","text":"`+x+`"}`)
	}
	body := `{"token":"` + token + `","items":[` + strings.Join(items, ",") + `]}`
	resp, err := http.Post(strings.Replace(mockURL, "/v1/mcp", "/__mock/push", 1), "application/json", bytes.NewBufferString(body))
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
}

func TestHandshakeListAndTypedCalls(t *testing.T) {
	for _, mode := range []string{"json", "sse"} {
		t.Run(mode, func(t *testing.T) {
			ctx := context.Background()
			c := mk(t, tok(), mode)
			tools, err := c.ListTools(ctx)
			if err != nil || len(tools) != 127 {
				t.Fatalf("tools=%d err=%v", len(tools), err)
			}
			if c.ServerInfo["name"] != "arious-agents" {
				t.Fatalf("server info %v", c.ServerInfo)
			}
			me, err := c.Whoami(ctx, ariousmcp.WhoamiArgs{})
			if err != nil || me.Structured["display_name"] != "Mock Agent" {
				t.Fatalf("whoami %v %v", me, err)
			}
			orgs, err := c.ListOrganizations(ctx, ariousmcp.ListOrganizationsArgs{})
			var o struct {
				Organizations []struct{ ID string } `json:"organizations"`
			}
			if err != nil || orgs.Decode(&o) != nil || o.Organizations[0].ID != "org-1" {
				t.Fatalf("orgs %v %v", orgs, err)
			}
			h, err := c.GetHandbook(ctx, ariousmcp.GetHandbookArgs{Section: "formatting"})
			if err != nil || !strings.Contains(h.Text, "formatting") {
				t.Fatalf("handbook %v %v", h, err)
			}
			g, err := c.SearchAppGuide(ctx, ariousmcp.SearchAppGuideArgs{Query: "calls"})
			if err != nil || g.Structured["results"] == nil {
				t.Fatalf("guide %v %v", g, err)
			}
		})
	}
}

func TestPathTokenURL(t *testing.T) {
	c, err := ariousmcp.New(ariousmcp.WithURL(mockURL + "/t/" + tok()))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.Whoami(context.Background(), ariousmcp.WhoamiArgs{}); err != nil {
		t.Fatal(err)
	}
}

func TestAuthErrorNotRetriedAndTokenHidden(t *testing.T) {
	c := mk(t, "wrong-token-xyz", "json")
	_, err := c.Whoami(context.Background(), ariousmcp.WhoamiArgs{})
	var ae *ariousmcp.AuthError
	if !errors.As(err, &ae) || ae.Status != 401 || strings.Contains(err.Error(), "wrong-token-xyz") {
		t.Fatalf("got %v", err)
	}
}

func TestConfigErrors(t *testing.T) {
	t.Setenv("ARIOUS_MCP_TOKEN", "")
	if _, err := ariousmcp.New(); !errors.Is(err, ariousmcp.ErrConfig) {
		t.Fatalf("want ErrConfig, got %v", err)
	}
	c, _ := ariousmcp.New(ariousmcp.WithToken("x"), ariousmcp.WithURL("http://127.0.0.1:1"))
	_, err := c.SendMessage(context.Background(), ariousmcp.SendMessageArgs{ConversationID: "c", Text: "t"})
	if !errors.Is(err, ariousmcp.ErrConfig) {
		t.Fatalf("want ErrConfig for missing model name, got %v", err)
	}
}

func TestToolAndProtocolErrors(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	_, err := c.CallTool(ctx, "mock_tool_error", nil)
	var te *ariousmcp.ToolError
	if !errors.As(err, &te) || !strings.Contains(te.Message, "tool-level") {
		t.Fatalf("got %v", err)
	}
	_, err = c.CallTool(ctx, "mock_protocol_error", nil)
	var pe *ariousmcp.ProtocolError
	if !errors.As(err, &pe) || pe.Code != -32602 {
		t.Fatalf("got %v", err)
	}
	if _, err = c.CallTool(ctx, "does_not_exist", nil); !errors.As(err, &pe) {
		t.Fatalf("got %v", err)
	}
	soft := mk(t, tok(), "json", ariousmcp.WithToolErrorsAsResults())
	r, err := soft.CallTool(ctx, "mock_tool_error", nil)
	if err != nil || !r.IsError {
		t.Fatalf("got %v %v", r, err)
	}
	if _, err = c.SearchAppGuide(ctx, ariousmcp.SearchAppGuideArgs{}); !errors.As(err, &te) {
		// query is required: the mock answers with an isError result
		t.Fatalf("missing arg: %v", err)
	}
}

func TestRetries(t *testing.T) {
	ctx := context.Background()
	for _, mode := range []string{"error", "ratelimit"} {
		if _, err := mk(t, tok(), mode).Whoami(ctx, ariousmcp.WhoamiArgs{}); err != nil {
			t.Fatalf("%s: %v", mode, err)
		}
	}
	_, err := mk(t, tok(), "error", ariousmcp.WithMaxRetries(1)).Whoami(ctx, ariousmcp.WhoamiArgs{})
	var se *ariousmcp.ServerError
	if !errors.As(err, &se) || se.Status != 500 {
		t.Fatalf("got %v", err)
	}
	_, err = mk(t, tok(), "ratelimit", ariousmcp.WithMaxRetries(0)).Whoami(ctx, ariousmcp.WhoamiArgs{})
	var rl *ariousmcp.RateLimitError
	if !errors.As(err, &rl) || rl.RetryAfterSeconds != 0 {
		t.Fatalf("got %v", err)
	}
}

func TestNonIdempotentRetryRules(t *testing.T) {
	ctx := context.Background()
	args := ariousmcp.CreateUploadURLArgs{ConversationID: "c", Filename: "a", Size: 1}
	var se *ariousmcp.ServerError
	if _, err := mk(t, tok(), "error").CreateUploadURL(ctx, args); !errors.As(err, &se) {
		t.Fatalf("5xx must not be retried for a non-idempotent tool: %v", err)
	}
	if _, err := mk(t, tok(), "ratelimit").CreateUploadURL(ctx, args); err != nil {
		t.Fatalf("429 is always retried: %v", err)
	}
}

func TestSendMessageSignsAndIsIdempotent(t *testing.T) {
	ctx := context.Background()
	token := tok()
	m, err := mk(t, token, "error").SendMessage(ctx, ariousmcp.SendMessageArgs{ConversationID: "c1", Text: "hello"})
	if err != nil || !strings.HasSuffix(m.Structured["text"].(string), "Test Model") {
		t.Fatalf("%v %v", m, err)
	}
	a, _ := mk(t, token, "json").SendMessage(ctx, ariousmcp.SendMessageArgs{ConversationID: "c1", Text: "hi", ClientMessageID: "fixed-1"})
	b, _ := mk(t, token, "json").SendMessage(ctx, ariousmcp.SendMessageArgs{ConversationID: "c1", Text: "hi", ClientMessageID: "fixed-1"})
	if b.Structured["deduplicated"] != true || a.Structured["message_id"] != b.Structured["message_id"] {
		t.Fatalf("not deduplicated: %v %v", a.Structured, b.Structured)
	}
	o, _ := mk(t, token, "json").SendMessage(ctx, ariousmcp.SendMessageArgs{ConversationID: "c", Text: "x", ModelName: "Other"})
	if !strings.HasSuffix(o.Structured["text"].(string), "Other") {
		t.Fatalf("explicit model name lost: %v", o.Structured)
	}
}

func TestTransportError(t *testing.T) {
	c, _ := ariousmcp.New(ariousmcp.WithToken("t"), ariousmcp.WithURL("http://127.0.0.1:1/v1/mcp"),
		ariousmcp.WithMaxRetries(1), ariousmcp.WithBackoff(time.Millisecond))
	_, err := c.Whoami(context.Background(), ariousmcp.WhoamiArgs{})
	var te *ariousmcp.TransportError
	if !errors.As(err, &te) {
		t.Fatalf("got %v", err)
	}
}

func TestContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := mk(t, tok(), "json").Whoami(ctx, ariousmcp.WhoamiArgs{}); !errors.Is(err, context.Canceled) {
		t.Fatalf("got %v", err)
	}
}

func TestWatchUpdatesAcksAfterBatch(t *testing.T) {
	token := tok()
	c := mk(t, token, "json")
	push(t, token, "a", "b")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var seen []string
	stop := errors.New("stop")
	err := c.WatchUpdates(ctx, ariousmcp.WatchOptions{WaitSeconds: -1}, func(_ context.Context, u ariousmcp.Update) error {
		seen = append(seen, u["text"].(string))
		if len(seen) == 2 {
			return stop // handler failed mid-batch: the batch must replay
		}
		return nil
	})
	if !errors.Is(err, stop) {
		t.Fatalf("got %v", err)
	}
	r, _ := c.GetUpdates(context.Background(), ariousmcp.GetUpdatesArgs{})
	if n := len(r.Structured["updates"].([]any)); n != 2 {
		t.Fatalf("batch should replay, got %d updates", n)
	}
	var got []string
	err = c.WatchUpdates(ctx, ariousmcp.WatchOptions{WaitSeconds: -1}, func(_ context.Context, u ariousmcp.Update) error {
		got = append(got, u["text"].(string))
		if len(got) == 2 {
			push(t, token, "c")
		}
		if len(got) == 3 {
			cancel()
		}
		return nil
	})
	if !errors.Is(err, context.Canceled) || strings.Join(got, "") != "abc" {
		t.Fatalf("err=%v got=%v", err, got)
	}
}

func TestUploadAndSend(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	r, err := c.UploadAndSend(ctx, "conv", []byte("hello"), ariousmcp.UploadOptions{Filename: "a.txt", Caption: "cap"})
	if err != nil || r.Structured["size_bytes"] != float64(5) {
		t.Fatalf("%v %v", r, err)
	}
	tk, err := c.UploadAndSend(ctx, "conv", []byte("abc"), ariousmcp.UploadOptions{Filename: "c.txt", SkipSend: true})
	if err != nil || !strings.HasPrefix(tk.Structured["upload_id"].(string), "up-") {
		t.Fatalf("%v %v", tk, err)
	}
	p := filepath.Join(t.TempDir(), "b.bin")
	if err := os.WriteFile(p, bytes.Repeat([]byte{1}, 1000), 0o600); err != nil {
		t.Fatal(err)
	}
	r, err = c.UploadAndSendFile(ctx, "conv", p, ariousmcp.UploadOptions{})
	if err != nil || r.Structured["size_bytes"] != float64(1000) {
		t.Fatalf("%v %v", r, err)
	}
	if _, err := c.UploadAndSend(ctx, "conv", []byte("x"), ariousmcp.UploadOptions{}); !errors.Is(err, ariousmcp.ErrConfig) {
		t.Fatalf("want ErrConfig, got %v", err)
	}
}

func mockActions(t *testing.T, conv string) []string {
	t.Helper()
	resp, err := http.Get(strings.Replace(mockURL, "/v1/mcp", "/__mock/log", 1))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	var log struct {
		Actions []struct {
			ConversationID string `json:"conversation_id"`
			Action         string `json:"action"`
		} `json:"actions"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&log); err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, a := range log.Actions {
		if a.ConversationID == conv {
			out = append(out, a.Action)
		}
	}
	return out
}

func TestChatActions(t *testing.T) {
	ctx := context.Background()
	for _, mode := range []string{"json", "sse"} {
		c := mk(t, tok(), mode)
		conv := "conv-act-" + mode
		if len(ariousmcp.ChatActions()) != 11 || !ariousmcp.ChatActionCancel.Valid() || ariousmcp.ChatAction("dance").Valid() {
			t.Fatal("ChatAction enum is wrong")
		}
		steps := []func() error{
			func() error {
				_, err := c.SendChatAction(ctx, ariousmcp.SendChatActionArgs{ConversationID: conv, Action: ariousmcp.ChatActionUploadPhoto})
				return err
			},
			func() error {
				_, err := c.SendChatAction(ctx, ariousmcp.SendChatActionArgs{ConversationID: conv, Action: ariousmcp.ChatActionCancel})
				return err
			},
			func() error { // backward compatible: no action means typing
				_, err := c.SendTyping(ctx, ariousmcp.SendTypingArgs{ConversationID: conv})
				return err
			},
			func() error {
				_, err := c.SendTyping(ctx, ariousmcp.SendTypingArgs{ConversationID: conv, Action: ariousmcp.ChatActionRecordVoice})
				return err
			},
		}
		for _, s := range steps {
			if err := s(); err != nil {
				t.Fatal(err)
			}
		}
		if got := strings.Join(mockActions(t, conv), ","); got != "upload_photo,cancel,typing,record_voice" {
			t.Fatalf("%s: %s", mode, got)
		}
	}
}

func TestUnknownChatActionIsToolError(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	var te *ariousmcp.ToolError
	_, err := c.SendChatAction(ctx, ariousmcp.SendChatActionArgs{ConversationID: "conv-bad", Action: "dance"})
	if !errors.As(err, &te) || !strings.Contains(te.Message, "unknown action") {
		t.Fatalf("got %v", err)
	}
	if _, err = c.SendChatAction(ctx, ariousmcp.SendChatActionArgs{ConversationID: "conv-bad"}); !errors.As(err, &te) {
		t.Fatalf("missing action: %v", err)
	}
}

func TestSearchAndSendGif(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	r, err := c.SearchGifs(ctx, ariousmcp.SearchGifsArgs{})
	if err != nil {
		t.Fatal(err)
	}
	trending, err := ariousmcp.DecodeSearchGifs(r)
	if err != nil || len(trending.Gifs) != 6 || trending.Busy {
		t.Fatalf("%+v %v", trending, err)
	}
	r, err = c.SearchGifs(ctx, ariousmcp.SearchGifsArgs{Query: "thumbs up", Limit: ariousmcp.Ptr(int64(1))})
	if err != nil {
		t.Fatal(err)
	}
	found, _ := ariousmcp.DecodeSearchGifs(r)
	if len(found.Gifs) != 1 || found.Gifs[0].GifID != "gif-001" || found.Gifs[0].Width != 480 ||
		found.Gifs[0].ContentType != "image/gif" || found.Gifs[0].Source != "library" ||
		!strings.HasPrefix(found.Gifs[0].PreviewURL, "http") {
		t.Fatalf("%+v", found)
	}
	r, _ = c.SearchGifs(ctx, ariousmcp.SearchGifsArgs{Query: "busy"})
	if busy, _ := ariousmcp.DecodeSearchGifs(r); !busy.Busy {
		t.Fatal("busy flag lost")
	}
	r, err = c.SendGif(ctx, ariousmcp.SendGifArgs{ConversationID: "conv-gif", GifID: "gif-001", Caption: "nice", Silent: ariousmcp.Ptr(true)})
	if err != nil {
		t.Fatal(err)
	}
	sent, err := ariousmcp.DecodeSendGif(r)
	if err != nil || sent.GifID != "gif-001" || sent.ConversationID != "conv-gif" ||
		!strings.HasPrefix(sent.MessageID, "msg-gif-") || !strings.HasPrefix(sent.AttachmentID, "att-gif-") || sent.SentViaGrantName != "" {
		t.Fatalf("%+v %v", sent, err)
	}
}

func TestGifErrors(t *testing.T) {
	ctx := context.Background()
	c := mk(t, tok(), "json")
	var te *ariousmcp.ToolError
	if _, err := c.SearchGifs(ctx, ariousmcp.SearchGifsArgs{Limit: ariousmcp.Ptr(int64(26))}); !errors.As(err, &te) {
		t.Fatalf("limit: %v", err)
	}
	if _, err := c.SendGif(ctx, ariousmcp.SendGifArgs{ConversationID: "c", GifID: "nope"}); !errors.As(err, &te) {
		t.Fatalf("gif id: %v", err)
	}
	bare, _ := ariousmcp.New(ariousmcp.WithToken("x"), ariousmcp.WithURL("http://127.0.0.1:1"))
	if _, err := bare.SendGif(ctx, ariousmcp.SendGifArgs{ConversationID: "c", GifID: "gif-001"}); !errors.Is(err, ariousmcp.ErrConfig) {
		t.Fatalf("model name: %v", err)
	}
}
