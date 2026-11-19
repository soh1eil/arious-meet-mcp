// Package ariousmcp is a client for the Arious Meet MCP server
// (https://api.ariousmeet.com/connect): initialize handshake, tools/list,
// tools/call over Streamable HTTP (JSON or SSE replies), retries, typed errors
// and one typed method per server tool.
package ariousmcp

//go:generate go run ./tools/generate

import (
	"bytes"
	"context"
	crand "crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// DefaultURL is the production endpoint.
const DefaultURL = "https://api.ariousmeet.com/v1/mcp"

const (
	protocolVersion = "2025-06-18"
	sdkName         = "arious-meet-mcp-go"
	sdkVersion      = "0.3.0"
)

// ToolMeta is the retry-relevant annotation set of one tool.
type ToolMeta struct {
	ReadOnly        bool
	Idempotent      bool
	ClientMessageID bool
	ModelName       bool
}

// ToolResult is the result of tools/call.
type ToolResult struct {
	// Text is every text content block joined by newlines.
	Text string
	// Structured is structuredContent when the server sent one.
	Structured map[string]any
	// Content holds the raw content blocks.
	Content []map[string]any
	IsError bool

	rawStructured json.RawMessage
}

// Data returns Structured if present, else the text parsed as JSON, else the text.
func (r *ToolResult) Data() any {
	if r.Structured != nil {
		return r.Structured
	}
	var v any
	if err := json.Unmarshal([]byte(r.Text), &v); err == nil {
		return v
	}
	return r.Text
}

// Decode unmarshals the structured content (or, failing that, the text) into v.
func (r *ToolResult) Decode(v any) error {
	if r.rawStructured != nil {
		return json.Unmarshal(r.rawStructured, v)
	}
	return json.Unmarshal([]byte(r.Text), v)
}

// Option configures New.
type Option func(*Client)

// WithToken sets the agent token (default: env ARIOUS_MCP_TOKEN).
func WithToken(t string) Option { return func(c *Client) { c.token = t } }

// WithURL sets the endpoint (default DefaultURL). A /v1/mcp/t/<token> URL needs no token.
func WithURL(u string) Option { return func(c *Client) { c.url = u } }

// WithModelName sets the real model name used to sign messages.
func WithModelName(n string) Option { return func(c *Client) { c.modelName = n } }

// WithHTTPClient replaces the http.Client (default timeout 60s).
func WithHTTPClient(h *http.Client) Option { return func(c *Client) { c.http = h } }

// WithMaxRetries sets retries on 429/5xx/network errors (default 3).
func WithMaxRetries(n int) Option { return func(c *Client) { c.maxRetries = n } }

// WithBackoff sets the base backoff (default 500ms).
func WithBackoff(d time.Duration) Option { return func(c *Client) { c.backoff = d } }

// WithToolErrorsAsResults makes CallTool return the *ToolResult with IsError set
// instead of a *ToolError.
func WithToolErrorsAsResults() Option { return func(c *Client) { c.toolErrorsAsResults = true } }

// Client talks to one Arious Meet MCP endpoint. It is safe for concurrent use.
type Client struct {
	url                 string
	token               string
	modelName           string
	http                *http.Client
	maxRetries          int
	backoff             time.Duration
	toolErrorsAsResults bool

	mu          sync.Mutex
	sessionID   string
	initialized bool
	nextID      atomic.Int64

	// ServerInfo is filled by the initialize handshake.
	ServerInfo map[string]any
}

// New builds a client. It does no I/O; the handshake happens on first use.
func New(opts ...Option) (*Client, error) {
	c := &Client{
		url:        DefaultURL,
		http:       &http.Client{Timeout: 60 * time.Second},
		maxRetries: 3,
		backoff:    500 * time.Millisecond,
	}
	c.token = os.Getenv("ARIOUS_MCP_TOKEN")
	for _, o := range opts {
		o(c)
	}
	if c.token == "" && !strings.Contains(c.url, "/mcp/t/") {
		return nil, fmt.Errorf("%w: no token: use WithToken, set ARIOUS_MCP_TOKEN, or use a /v1/mcp/t/<token> URL", ErrConfig)
	}
	return c, nil
}

// SetModelName changes the model name used to sign messages.
func (c *Client) SetModelName(n string) {
	c.mu.Lock()
	c.modelName = n
	c.mu.Unlock()
}

func (c *Client) redact(s string) string {
	if c.token != "" {
		s = strings.ReplaceAll(s, c.token, "***")
	}
	if i := strings.Index(c.url, "/mcp/t/"); i >= 0 {
		if tail := c.url[i+len("/mcp/t/"):]; len(tail) > 0 {
			s = strings.ReplaceAll(s, tail, "***")
		}
	}
	return s
}

type rpcMessage struct {
	ID     json.RawMessage `json:"id"`
	Result json.RawMessage `json:"result"`
	Error  *struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

// parseBody picks the JSON-RPC message answering id from a JSON or SSE body.
func parseBody(contentType string, body []byte, id int64) (*rpcMessage, error) {
	want := strconv.FormatInt(id, 10)
	if strings.Contains(contentType, "text/event-stream") {
		text := strings.ReplaceAll(string(body), "\r\n", "\n")
		for _, block := range strings.Split(text, "\n\n") {
			var data []string
			for _, line := range strings.Split(block, "\n") {
				if strings.HasPrefix(line, "data:") {
					data = append(data, strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
				}
			}
			joined := strings.Join(data, "\n")
			if strings.TrimSpace(joined) == "" {
				continue
			}
			var m rpcMessage
			if json.Unmarshal([]byte(joined), &m) != nil {
				continue
			}
			if string(m.ID) == want && (m.Result != nil || m.Error != nil) {
				return &m, nil
			}
		}
		return nil, &ProtocolError{Message: "SSE stream ended without a reply to request " + want}
	}
	var m rpcMessage
	if err := json.Unmarshal(body, &m); err != nil {
		return nil, &ProtocolError{Message: "reply is not valid JSON: " + err.Error()}
	}
	return &m, nil
}

func httpError(status int, body []byte, retryAfter float64) error {
	detail := strings.TrimSpace(string(body))
	if len(detail) > 300 {
		detail = detail[:300]
	}
	var b struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(body, &b) == nil && b.Error != "" {
		detail = b.Error
	}
	msg := fmt.Sprintf("HTTP %d: %s", status, detail)
	switch status {
	case 401, 403:
		return &AuthError{Status: status, Message: msg}
	case 429:
		return &RateLimitError{Message: msg, RetryAfterSeconds: retryAfter}
	}
	return &ServerError{Status: status, Message: msg}
}

func (c *Client) delay(attempt int, retryAfter float64) time.Duration {
	if retryAfter >= 0 {
		return time.Duration(math.Min(retryAfter, 60) * float64(time.Second))
	}
	base := math.Min(float64(c.backoff)*math.Pow(2, float64(attempt)), float64(20*time.Second))
	return time.Duration(base * (0.5 + rand.Float64()/2)) //nolint:gosec // jitter only
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

// canRetryCall: a 429 means the call never ran. After a 5xx or network error only
// read-only/idempotent tools and calls carrying a client_message_id are safe.
func canRetryCall(name string, args map[string]any, status int) bool {
	if status == 429 {
		return true
	}
	m, ok := toolMeta[name]
	if !ok {
		return false
	}
	if m.ReadOnly || m.Idempotent {
		return true
	}
	_, has := args["client_message_id"]
	return has
}

func (c *Client) post(ctx context.Context, id int64, payload any, retryOK func(status int) bool) (*rpcMessage, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	for attempt := 0; ; attempt++ {
		status := 0
		retryAfter := -1.0
		var failure error
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url, bytes.NewReader(body))
		if err != nil {
			return nil, &TransportError{Err: fmt.Errorf("%s", c.redact(err.Error()))}
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json, text/event-stream")
		req.Header.Set("MCP-Protocol-Version", protocolVersion)
		req.Header.Set("User-Agent", sdkName+"/"+sdkVersion)
		if c.token != "" {
			req.Header.Set("Authorization", "Bearer "+c.token)
		}
		c.mu.Lock()
		sid := c.sessionID
		c.mu.Unlock()
		if sid != "" {
			req.Header.Set("Mcp-Session-Id", sid)
		}
		resp, err := c.http.Do(req)
		if err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			failure = &TransportError{Err: fmt.Errorf("%s", c.redact(err.Error()))}
		} else {
			data, rerr := io.ReadAll(resp.Body)
			_ = resp.Body.Close()
			status = resp.StatusCode
			if v, perr := strconv.ParseFloat(resp.Header.Get("Retry-After"), 64); perr == nil && v >= 0 {
				retryAfter = v
			}
			switch {
			case rerr != nil:
				if ctx.Err() != nil {
					return nil, ctx.Err()
				}
				failure = &TransportError{Err: fmt.Errorf("%s", c.redact(rerr.Error()))}
				status = 0
			case status < 400:
				if m, ok := payload.(map[string]any); ok && m["method"] == "initialize" {
					if s := resp.Header.Get("Mcp-Session-Id"); s != "" {
						c.mu.Lock()
						c.sessionID = s
						c.mu.Unlock()
					}
				}
				if status == http.StatusAccepted || len(bytes.TrimSpace(data)) == 0 {
					return nil, nil
				}
				return parseBody(resp.Header.Get("Content-Type"), data, id)
			default:
				failure = httpError(status, data, retryAfter)
			}
		}
		_, isAuth := failure.(*AuthError)
		retryable := status == 0 || status == 429 || status >= 500
		if isAuth || !retryable || attempt >= c.maxRetries || !retryOK(status) {
			return nil, failure
		}
		if err := sleep(ctx, c.delay(attempt, retryAfter)); err != nil {
			return nil, err
		}
	}
}

func (c *Client) rpc(ctx context.Context, method string, params any, retryOK func(int) bool) (json.RawMessage, error) {
	if retryOK == nil {
		retryOK = func(int) bool { return true }
	}
	id := c.nextID.Add(1)
	payload := map[string]any{"jsonrpc": "2.0", "id": id, "method": method}
	if params != nil {
		payload["params"] = params
	}
	msg, err := c.post(ctx, id, payload, retryOK)
	if err != nil || msg == nil {
		return nil, err
	}
	if msg.Error != nil {
		return nil, &ProtocolError{Code: msg.Error.Code, Message: msg.Error.Message}
	}
	return msg.Result, nil
}

// Initialize runs the handshake. It is called automatically on first use.
func (c *Client) Initialize(ctx context.Context) error {
	res, err := c.rpc(ctx, "initialize", map[string]any{
		"protocolVersion": protocolVersion,
		"capabilities":    map[string]any{},
		"clientInfo":      map[string]any{"name": sdkName, "version": sdkVersion},
	}, nil)
	if err != nil {
		return err
	}
	var r struct {
		ServerInfo map[string]any `json:"serverInfo"`
	}
	_ = json.Unmarshal(res, &r)
	c.ServerInfo = r.ServerInfo
	if _, err := c.post(ctx, 0, map[string]any{"jsonrpc": "2.0", "method": "notifications/initialized"}, func(int) bool { return true }); err != nil {
		return err
	}
	return nil
}

func (c *Client) ensureInitialized(ctx context.Context) error {
	c.mu.Lock()
	done := c.initialized
	c.mu.Unlock()
	if done {
		return nil
	}
	// A second goroutine may race into Initialize; both handshakes are harmless.
	if err := c.Initialize(ctx); err != nil {
		return err
	}
	c.mu.Lock()
	c.initialized = true
	c.mu.Unlock()
	return nil
}

// ListTools returns the live tool catalogue as raw maps (name, description, inputSchema...).
func (c *Client) ListTools(ctx context.Context) ([]map[string]any, error) {
	if err := c.ensureInitialized(ctx); err != nil {
		return nil, err
	}
	res, err := c.rpc(ctx, "tools/list", nil, nil)
	if err != nil {
		return nil, err
	}
	var r struct {
		Tools []map[string]any `json:"tools"`
	}
	if err := json.Unmarshal(res, &r); err != nil {
		return nil, &ProtocolError{Message: "bad tools/list result: " + err.Error()}
	}
	return r.Tools, nil
}

// Ping sends a ping.
func (c *Client) Ping(ctx context.Context) error {
	if err := c.ensureInitialized(ctx); err != nil {
		return err
	}
	_, err := c.rpc(ctx, "ping", nil, nil)
	return err
}

// callStruct marshals a generated args struct and calls the tool.
func (c *Client) callStruct(ctx context.Context, name string, args any) (*ToolResult, error) {
	raw, err := json.Marshal(args)
	if err != nil {
		return nil, err
	}
	m := map[string]any{}
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, err
	}
	return c.CallTool(ctx, name, m)
}

// CallTool calls any tool by name. nil-valued arguments are dropped, model_name
// and client_message_id are filled in where the tool takes them. A tool that
// answers isError returns a *ToolError (unless WithToolErrorsAsResults).
func (c *Client) CallTool(ctx context.Context, name string, args map[string]any) (*ToolResult, error) {
	a := map[string]any{}
	for k, v := range args {
		if v != nil {
			a[k] = v
		}
	}
	if meta, ok := toolMeta[name]; ok {
		if s, _ := a["model_name"].(string); meta.ModelName && s == "" {
			c.mu.Lock()
			mn := c.modelName
			c.mu.Unlock()
			if mn == "" {
				return nil, fmt.Errorf("%w: %s needs a model name: use WithModelName or set model_name (sign every message with your real model name)", ErrConfig, name)
			}
			a["model_name"] = mn
		}
		if s, _ := a["client_message_id"].(string); meta.ClientMessageID && s == "" {
			a["client_message_id"] = newUUID()
		}
	}
	if err := c.ensureInitialized(ctx); err != nil {
		return nil, err
	}
	res, err := c.rpc(ctx, "tools/call", map[string]any{"name": name, "arguments": a},
		func(status int) bool { return canRetryCall(name, a, status) })
	if err != nil {
		return nil, err
	}
	var raw struct {
		Content           []map[string]any `json:"content"`
		StructuredContent json.RawMessage  `json:"structuredContent"`
		IsError           bool             `json:"isError"`
	}
	if err := json.Unmarshal(res, &raw); err != nil {
		return nil, &ProtocolError{Message: "tools/call result is not an object"}
	}
	out := &ToolResult{Content: raw.Content, IsError: raw.IsError}
	var texts []string
	for _, b := range raw.Content {
		if b["type"] == "text" {
			s, _ := b["text"].(string)
			texts = append(texts, s)
		}
	}
	out.Text = strings.Join(texts, "\n")
	if len(raw.StructuredContent) > 0 && string(raw.StructuredContent) != "null" {
		out.rawStructured = raw.StructuredContent
		_ = json.Unmarshal(raw.StructuredContent, &out.Structured)
	}
	if out.IsError && !c.toolErrorsAsResults {
		msg := out.Text
		if msg == "" {
			msg = "tool error"
		}
		if ce := asContextConflict(out, msg); ce != nil {
			return out, ce
		}
		return out, &ToolError{Message: msg, Result: out}
	}
	return out, nil
}

func newUUID() string {
	var b [16]byte
	if _, err := crand.Read(b[:]); err != nil {
		for i := range b {
			b[i] = byte(rand.Intn(256)) //nolint:gosec // fallback only
		}
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

// Ptr returns a pointer to v, for optional bool/number arguments.
func Ptr[T any](v T) *T { return &v }
