package ariousmcp

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
)

// Update is one item of a get_updates answer (kind, conversation_id, ...).
type Update map[string]any

// Kind returns the update's kind ("mention", "direct_message", ...).
func (u Update) Kind() string { s, _ := u["kind"].(string); return s }

// WatchOptions configures WatchUpdates.
type WatchOptions struct {
	// Only restricts the kinds returned (default: everything).
	Only []string
	// WaitSeconds is the long-poll length, 0-25 (default 25; set -1 to poll without waiting).
	WaitSeconds int
	// NoAck disables acknowledging batches.
	NoAck bool
	// MaxTextChars truncates each message text (0 = server default).
	MaxTextChars int
}

// WatchUpdates long-polls get_updates until ctx is cancelled or handler returns
// an error, calling handler for every update. After handler has accepted a whole
// batch the batch's cursor is acknowledged with ack_updates (at-least-once: if
// handler fails, the batch is replayed next time). Rate limits, 5xx and network
// errors back off and continue; auth and tool errors are returned.
func (c *Client) WatchUpdates(ctx context.Context, opts WatchOptions, handler func(context.Context, Update) error) error {
	wait := opts.WaitSeconds
	switch {
	case wait == 0:
		wait = 25
	case wait < 0:
		wait = 0
	}
	cursor := ""
	failures := 0
	for ctx.Err() == nil {
		args := GetUpdatesArgs{WaitSeconds: Ptr(int64(wait)), Only: opts.Only, Cursor: cursor}
		if opts.MaxTextChars > 0 {
			args.MaxTextChars = Ptr(int64(opts.MaxTextChars))
		}
		res, err := c.GetUpdates(ctx, args)
		if err != nil {
			var rl *RateLimitError
			var se *ServerError
			var te *TransportError
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if errors.As(err, &rl) || errors.As(err, &se) || errors.As(err, &te) {
				failures++
				if failures > 6 {
					failures = 6
				}
				if serr := sleep(ctx, c.delay(failures, -1)); serr != nil {
					return serr
				}
				continue
			}
			return err
		}
		failures = 0
		var data struct {
			Updates    []Update `json:"updates"`
			NextCursor string   `json:"next_cursor"`
		}
		if err := res.Decode(&data); err != nil {
			return &ProtocolError{Message: "bad get_updates result: " + err.Error()}
		}
		for _, u := range data.Updates {
			if err := handler(ctx, u); err != nil {
				return err
			}
		}
		if data.NextCursor != "" {
			cursor = data.NextCursor
			if !opts.NoAck && len(data.Updates) > 0 {
				if _, err := c.AckUpdates(ctx, AckUpdatesArgs{Cursor: data.NextCursor}); err != nil {
					return err
				}
			}
		}
	}
	return ctx.Err()
}

// UploadOptions configures UploadAndSend.
type UploadOptions struct {
	// Filename is required when the data has no name of its own.
	Filename string
	// MIME defaults to a guess from the filename.
	MIME string
	// Caption is sent with the file.
	Caption string
	// SkipSend stops after the upload; the returned result is create_upload_url's
	// (its upload_id can be passed to any tool).
	SkipSend bool
	// Extra holds further send_file arguments (reply_to_id, silent, as_voice...).
	Extra map[string]any
}

// UploadAndSend runs create_upload_url, PUTs data and calls send_file.
func (c *Client) UploadAndSend(ctx context.Context, conversationID string, data []byte, opts UploadOptions) (*ToolResult, error) {
	if opts.Filename == "" {
		return nil, fmt.Errorf("%w: UploadOptions.Filename is required", ErrConfig)
	}
	mt := opts.MIME
	if mt == "" {
		mt = mime.TypeByExtension(filepath.Ext(opts.Filename))
	}
	if mt == "" {
		mt = "application/octet-stream"
	}
	ticket, err := c.CreateUploadURL(ctx, CreateUploadURLArgs{
		ConversationID: conversationID, Filename: opts.Filename, Size: int64(len(data)), Mime: mt,
	})
	if err != nil {
		return nil, err
	}
	var info struct {
		UploadURL string            `json:"upload_url"`
		UploadID  string            `json:"upload_id"`
		Headers   map[string]string `json:"headers"`
	}
	if err := ticket.Decode(&info); err != nil || info.UploadURL == "" {
		return nil, &ProtocolError{Message: "create_upload_url returned no upload_url"}
	}
	if err := c.put(ctx, info.UploadURL, info.Headers, mt, data); err != nil {
		return nil, err
	}
	if opts.SkipSend {
		return ticket, nil
	}
	extra := map[string]any{}
	for k, v := range opts.Extra {
		extra[k] = v
	}
	extra["conversation_id"] = conversationID
	extra["upload_id"] = info.UploadID
	if opts.Caption != "" {
		extra["caption"] = opts.Caption
	}
	return c.CallTool(ctx, "send_file", extra)
}

// UploadAndSendFile reads path and calls UploadAndSend (Filename defaults to its base name).
func (c *Client) UploadAndSendFile(ctx context.Context, conversationID, path string, opts UploadOptions) (*ToolResult, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if opts.Filename == "" {
		opts.Filename = filepath.Base(path)
	}
	return c.UploadAndSend(ctx, conversationID, data, opts)
}

// put uploads without the bearer token: the URL itself is the credential.
func (c *Client) put(ctx context.Context, url string, headers map[string]string, mt string, data []byte) error {
	for attempt := 0; ; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPut, url, bytes.NewReader(data))
		if err != nil {
			return &TransportError{Err: fmt.Errorf("bad upload URL")}
		}
		req.Header.Set("Content-Type", mt)
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		var failure error
		status := 0
		resp, err := c.http.Do(req)
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			failure = &TransportError{Err: fmt.Errorf("upload failed: %s", c.redact(err.Error()))}
		} else {
			body, _ := io.ReadAll(resp.Body)
			_ = resp.Body.Close()
			status = resp.StatusCode
			if status < 400 {
				return nil
			}
			failure = httpError(status, body, -1)
		}
		_, isAuth := failure.(*AuthError)
		retryable := status == 0 || status == 429 || status >= 500
		if isAuth || !retryable || attempt >= c.maxRetries {
			return failure
		}
		if err := sleep(ctx, c.delay(attempt, -1)); err != nil {
			return err
		}
	}
}
