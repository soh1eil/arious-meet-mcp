namespace AriousMeet.Mcp;

/// <summary>Base class of every error thrown by this library.</summary>
public class McpException : Exception
{
    public McpException(string message) : base(message) { }
    public McpException(string message, Exception inner) : base(message, inner) { }
}

/// <summary>HTTP 401/403: the token is missing, wrong, expired or revoked.</summary>
public sealed class McpAuthException(string message, int status = 401) : McpException(message)
{
    public int Status { get; } = status;
}

/// <summary>HTTP 429 after retries ran out.</summary>
public sealed class McpRateLimitException(string message, TimeSpan? retryAfter = null) : McpException(message)
{
    public TimeSpan? RetryAfter { get; } = retryAfter;
}

/// <summary>The tool ran and answered <c>isError: true</c>.</summary>
public sealed class McpToolException(string message, string? tool = null) : McpException(message)
{
    public string? Tool { get; } = tool;
}

/// <summary>A JSON-RPC level error (unknown method/tool, invalid params, ...).</summary>
public sealed class McpProtocolException(string message, int? code = null) : McpException(message)
{
    public int? Code { get; } = code;
}

/// <summary>Network failure, timeout, or an unexpected HTTP status.</summary>
public sealed class McpTransportException(string message, int? status = null) : McpException(message)
{
    public int? Status { get; } = status;
}
