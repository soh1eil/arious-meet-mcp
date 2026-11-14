/// Base class of every error thrown by this package.
class McpException implements Exception {
  McpException(this.message);
  final String message;
  @override
  String toString() => '$runtimeType: $message';
}

/// HTTP 401/403: the token is missing, wrong, expired or revoked.
class McpAuthError extends McpException {
  McpAuthError(super.message, {this.status = 401});
  final int status;
}

/// HTTP 429: slow down. [retryAfter] is the server's hint, if any.
class McpRateLimitError extends McpException {
  McpRateLimitError(super.message, {this.retryAfter});
  final Duration? retryAfter;
}

/// The tool ran and refused (`isError: true`). [message] is the server's text.
class McpToolError extends McpException {
  McpToolError(super.message, {this.tool, this.result});
  final String? tool;
  final Map<String, dynamic>? result;
}

/// A JSON-RPC level error (bad method, bad params, unknown tool, ...).
class McpProtocolError extends McpException {
  McpProtocolError(super.message, {this.code});
  final int? code;
}

/// Network failure, timeout, or an HTTP status that is not 401/403/429.
class McpTransportError extends McpException {
  McpTransportError(super.message, {this.status});
  final int? status;
}
