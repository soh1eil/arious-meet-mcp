package ariousmcp

import (
	"errors"
	"fmt"
)

// ErrConfig is wrapped by every configuration problem (no token, no model name).
var ErrConfig = errors.New("ariousmcp: configuration error")

// AuthError is HTTP 401/403: bad, revoked or out-of-scope token. Never retried.
type AuthError struct {
	Status  int
	Message string
}

func (e *AuthError) Error() string { return fmt.Sprintf("ariousmcp: auth error: %s", e.Message) }

// RateLimitError is HTTP 429 that survived all retries.
type RateLimitError struct {
	Message string
	// RetryAfterSeconds is the server's Retry-After, or -1 when absent.
	RetryAfterSeconds float64
}

func (e *RateLimitError) Error() string { return fmt.Sprintf("ariousmcp: rate limited: %s", e.Message) }

// ServerError is HTTP 5xx (or another unexpected status) that survived all retries.
type ServerError struct {
	Status  int
	Message string
}

func (e *ServerError) Error() string { return fmt.Sprintf("ariousmcp: server error: %s", e.Message) }

// TransportError is a network failure or timeout that survived all retries.
type TransportError struct{ Err error }

func (e *TransportError) Error() string { return fmt.Sprintf("ariousmcp: transport error: %v", e.Err) }
func (e *TransportError) Unwrap() error { return e.Err }

// ProtocolError is a JSON-RPC error object or an unparseable reply.
type ProtocolError struct {
	Code    int
	Message string
}

func (e *ProtocolError) Error() string {
	return fmt.Sprintf("ariousmcp: protocol error %d: %s", e.Code, e.Message)
}

// ToolError means the tool ran and refused (isError: true). Message is the server's text.
type ToolError struct {
	Message string
	Result  *ToolResult
}

func (e *ToolError) Error() string { return "ariousmcp: tool error: " + e.Message }
