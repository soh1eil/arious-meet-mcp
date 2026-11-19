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
public class McpToolException(string message, string? tool = null, ToolResult? result = null) : McpException(message)
{
    public string? Tool { get; } = tool;

    /// <summary>The full refused result (structured content included), when known.</summary>
    public ToolResult? Result { get; } = result;
}

/// <summary>
/// <c>context_checkpoint</c> lost a race: someone else wrote a newer version. Merge your changes into
/// <see cref="Latest"/> and checkpoint again with <c>baseVersion: LatestVersion</c>. It is a
/// <see cref="McpToolException"/>, so existing handlers keep working.
/// </summary>
public sealed class ContextConflictException(
    string message,
    ToolResult result,
    long baseVersion,
    long latestVersion,
    ContextVersion? latest) : McpToolException(message, "context_checkpoint", result)
{
    /// <summary>The version you built on.</summary>
    public long BaseVersion { get; } = baseVersion;

    /// <summary>The version the server holds now.</summary>
    public long LatestVersion { get; } = latestVersion;

    /// <summary>The latest version's content, when the server sent it.</summary>
    public ContextVersion? Latest { get; } = latest;
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
