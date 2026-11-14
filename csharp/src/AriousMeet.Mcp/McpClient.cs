using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AriousMeet.Mcp;

/// <summary>Options for <see cref="McpClient"/>.</summary>
public sealed class McpClientOptions
{
    public const string DefaultBaseUrl = "https://api.ariousmeet.com/v1/mcp";

    /// <summary>Agent token. Never logged or included in messages.</summary>
    public string Token { get; set; } = "";

    public string BaseUrl { get; set; } = DefaultBaseUrl;

    /// <summary>Default <c>model_name</c> for every tool that takes one.</summary>
    public string? ModelName { get; set; }

    /// <summary>Use the <c>/t/{token}</c> URL form instead of the Authorization header.</summary>
    public bool TokenInPath { get; set; }

    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(60);
    public int MaxRetries { get; set; } = 3;
    public TimeSpan BackoffBase { get; set; } = TimeSpan.FromMilliseconds(500);

    /// <summary>Supply your own HttpClient (it will not be disposed by the client).</summary>
    public HttpClient? HttpClient { get; set; }
}

/// <summary>
/// Low-level Arious Meet MCP client with one generated method per tool.
/// Never prints the token. Retries HTTP 429 always, and 5xx / network failures
/// only for calls that are safe to repeat (read-only or idempotent tools, or
/// calls carrying a <c>client_message_id</c>, which this client fills in when
/// the tool accepts one).
/// </summary>
public sealed partial class McpClient : IDisposable
{
    public const string ProtocolVersion = "2025-06-18";
    private const string SdkVersion = "0.2.0";

    private readonly McpClientOptions _o;
    private readonly string _token;
    private readonly HttpClient _http;
    private readonly bool _ownsHttp;
    private readonly SemaphoreSlim _initLock = new(1, 1);
    private JsonObject? _initResult;
    private string? _sessionId;
    private long _id;

    public McpClient(McpClientOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        _o = options;
        _token = (options.Token ?? "").Trim();
        if (_token.Length == 0)
        {
            throw new ArgumentException("token must not be empty", nameof(options));
        }
        _ownsHttp = options.HttpClient is null;
        _http = options.HttpClient ?? new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
    }

    /// <summary>Reads <c>ARIOUS_MCP_TOKEN</c> (and optional <c>ARIOUS_MCP_URL</c>).</summary>
    public static McpClient FromEnvironment(string? modelName = null)
    {
        var t = Environment.GetEnvironmentVariable("ARIOUS_MCP_TOKEN");
        if (string.IsNullOrWhiteSpace(t))
        {
            throw new McpAuthException("ARIOUS_MCP_TOKEN is not set", 0);
        }
        var o = new McpClientOptions { Token = t, ModelName = modelName };
        var u = Environment.GetEnvironmentVariable("ARIOUS_MCP_URL");
        if (!string.IsNullOrEmpty(u))
        {
            o.BaseUrl = u;
        }
        return new McpClient(o);
    }

    /// <summary>Default <c>model_name</c>; settable after construction.</summary>
    public string? ModelName
    {
        get => _o.ModelName;
        set => _o.ModelName = value;
    }

    public override string ToString() => $"McpClient({_o.BaseUrl})";

    public void Dispose()
    {
        if (_ownsHttp)
        {
            _http.Dispose();
        }
        _initLock.Dispose();
    }

    private Uri Url()
    {
        if (_o.TokenInPath)
        {
            return new Uri($"{_o.BaseUrl.TrimEnd('/')}/t/{_token}/");
        }
        return new Uri(_o.BaseUrl);
    }

    private void ApplyHeaders(HttpRequestMessage req, bool sse)
    {
        req.Headers.TryAddWithoutValidation("Accept", sse ? "text/event-stream" : "application/json, text/event-stream");
        req.Headers.TryAddWithoutValidation("User-Agent", $"arious-meet-mcp-dotnet/{SdkVersion}");
        req.Headers.TryAddWithoutValidation("MCP-Protocol-Version", ProtocolVersion);
        if (!_o.TokenInPath)
        {
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
        }
        if (_sessionId is not null)
        {
            req.Headers.TryAddWithoutValidation("Mcp-Session-Id", _sessionId);
        }
    }

    /// <summary>The <c>initialize</c> handshake (once; later calls return the cached answer).</summary>
    public async Task<JsonObject> InitializeAsync(CancellationToken ct = default)
    {
        if (_initResult is not null)
        {
            return _initResult;
        }
        await _initLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (_initResult is not null)
            {
                return _initResult;
            }
            var res = await RpcAsync("initialize", new JsonObject
            {
                ["protocolVersion"] = ProtocolVersion,
                ["capabilities"] = new JsonObject(),
                ["clientInfo"] = new JsonObject { ["name"] = "arious-meet-mcp-dotnet", ["version"] = SdkVersion },
            }, true, ct).ConfigureAwait(false);
            await NotifyAsync("notifications/initialized", ct).ConfigureAwait(false);
            _initResult = res;
            return res;
        }
        finally
        {
            _initLock.Release();
        }
    }

    /// <summary><c>tools/list</c>.</summary>
    public async Task<IReadOnlyList<JsonObject>> ListToolsAsync(CancellationToken ct = default)
    {
        await InitializeAsync(ct).ConfigureAwait(false);
        var r = await RpcAsync("tools/list", new JsonObject(), true, ct).ConfigureAwait(false);
        return (r["tools"] as JsonArray)?.OfType<JsonObject>().ToList() ?? [];
    }

    /// <summary><c>ping</c>.</summary>
    public async Task PingAsync(CancellationToken ct = default)
    {
        await InitializeAsync(ct).ConfigureAwait(false);
        await RpcAsync("ping", new JsonObject(), true, ct).ConfigureAwait(false);
    }

    /// <summary>
    /// <c>tools/call</c>. Throws <see cref="McpToolException"/> when the tool answers
    /// <c>isError</c> unless <paramref name="throwOnError"/> is false.
    /// </summary>
    public async Task<ToolResult> CallToolAsync(
        string name,
        JsonObject? arguments = null,
        bool throwOnError = true,
        CancellationToken ct = default)
    {
        await InitializeAsync(ct).ConfigureAwait(false);
        var args = new JsonObject();
        if (arguments is not null)
        {
            foreach (var kv in arguments)
            {
                if (kv.Value is not null)
                {
                    args[kv.Key] = kv.Value.DeepClone();
                }
            }
        }
        var safe = false;
        if (ToolTraitsTable.TryGet(name, out var t))
        {
            safe = t.SafeToRepeat;
            if (t.HasModelName && !args.ContainsKey("model_name") && ModelName is not null)
            {
                args["model_name"] = ModelName;
            }
            if (t.RequiresModelName && !args.ContainsKey("model_name"))
            {
                throw new ArgumentException(
                    $"model_name is required by {name}: pass it or set McpClient.ModelName");
            }
            if (t.HasClientMessageId && !args.ContainsKey("client_message_id"))
            {
                args["client_message_id"] = Guid.NewGuid().ToString();
            }
        }
        if (args.ContainsKey("client_message_id"))
        {
            safe = true;
        }
        var res = await RpcAsync("tools/call", new JsonObject { ["name"] = name, ["arguments"] = args }, safe, ct)
            .ConfigureAwait(false);
        var content = res["content"] as JsonArray ?? [];
        var text = content.OfType<JsonObject>()
            .Where(b => (string?)b["type"] == "text")
            .Select(b => (string?)b["text"] ?? "")
            .FirstOrDefault() ?? "";
        var isError = res["isError"] is JsonValue v && v.TryGetValue<bool>(out var b2) && b2;
        var result = new ToolResult(text, (JsonArray)content.DeepClone(), res["structuredContent"] as JsonObject, isError);
        if (isError && throwOnError)
        {
            throw new McpToolException(text, name);
        }
        return result;
    }

    /// <summary>
    /// Opens the server-to-client SSE stream and yields each JSON-RPC notification;
    /// ends when the server closes it.
    /// </summary>
    public async IAsyncEnumerable<JsonObject> NotificationsAsync(
        string? conversationId = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        await InitializeAsync(ct).ConfigureAwait(false);
        var uri = Url();
        if (conversationId is not null)
        {
            uri = new Uri(uri + (uri.Query.Length > 0 ? "&" : "?") + "conversation_id=" + Uri.EscapeDataString(conversationId));
        }
        using var req = new HttpRequestMessage(HttpMethod.Get, uri);
        ApplyHeaders(req, true);
        HttpResponseMessage resp;
        try
        {
            resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        }
        catch (HttpRequestException e)
        {
            throw new McpTransportException("network error: " + e.GetType().Name);
        }
        using (resp)
        {
            if (!resp.IsSuccessStatusCode)
            {
                throw await StatusErrorAsync(resp).ConfigureAwait(false);
            }
            await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            using var reader = new StreamReader(stream, Encoding.UTF8);
            var parser = new SseParser();
            var buf = new char[4096];
            int n;
            while ((n = await reader.ReadAsync(buf.AsMemory(), ct).ConfigureAwait(false)) > 0)
            {
                foreach (var data in parser.Feed(new string(buf, 0, n)))
                {
                    JsonNode? node = null;
                    try
                    {
                        node = JsonNode.Parse(data);
                    }
                    catch (JsonException)
                    {
                        // ignore non-JSON events
                    }
                    if (node is JsonObject o)
                    {
                        yield return o;
                    }
                }
            }
        }
    }

    /// <summary>
    /// PUTs raw bytes to an absolute URL. Upload tickets carry their own
    /// credential, so no bearer header is sent.
    /// </summary>
    public async Task PutBytesAsync(
        string url,
        byte[] bytes,
        IReadOnlyDictionary<string, string>? headers = null,
        CancellationToken ct = default)
    {
        var attempt = 0;
        while (true)
        {
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Put, url) { Content = new ByteArrayContent(bytes) };
                if (headers is not null)
                {
                    foreach (var (k, v) in headers)
                    {
                        if (!req.Content.Headers.TryAddWithoutValidation(k, v))
                        {
                            req.Headers.TryAddWithoutValidation(k, v);
                        }
                    }
                }
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(_o.Timeout * 5);
                using var resp = await _http.SendAsync(req, cts.Token).ConfigureAwait(false);
                if (resp.IsSuccessStatusCode)
                {
                    return;
                }
                var s = (int)resp.StatusCode;
                if (!(s == 429 || s >= 500) || attempt >= _o.MaxRetries)
                {
                    throw await StatusErrorAsync(resp).ConfigureAwait(false);
                }
            }
            catch (Exception e) when (e is HttpRequestException or OperationCanceledException && !ct.IsCancellationRequested)
            {
                if (attempt >= _o.MaxRetries)
                {
                    throw new McpTransportException("upload failed: " + e.GetType().Name);
                }
            }
            await Task.Delay(Delay(attempt, null), ct).ConfigureAwait(false);
            attempt++;
        }
    }

    // ------------------------------------------------------------ internals

    private async Task NotifyAsync(string method, CancellationToken ct)
    {
        using var resp = await SendAsync(new JsonObject { ["jsonrpc"] = "2.0", ["method"] = method }, true, ct)
            .ConfigureAwait(false);
        if ((int)resp.StatusCode >= 400)
        {
            throw await StatusErrorAsync(resp).ConfigureAwait(false);
        }
    }

    private async Task<JsonObject> RpcAsync(string method, JsonObject args, bool retry, CancellationToken ct)
    {
        var id = Interlocked.Increment(ref _id);
        var body = new JsonObject { ["jsonrpc"] = "2.0", ["id"] = id, ["method"] = method, ["params"] = args };
        using var resp = await SendAsync(body, retry, ct).ConfigureAwait(false);
        if ((int)resp.StatusCode >= 400)
        {
            throw await StatusErrorAsync(resp).ConfigureAwait(false);
        }
        if (method == "initialize" && resp.Headers.TryGetValues("Mcp-Session-Id", out var sids))
        {
            var sid = sids.FirstOrDefault();
            if (!string.IsNullOrEmpty(sid))
            {
                _sessionId = sid;
            }
        }
        var ct2 = resp.Content.Headers.ContentType?.MediaType ?? "";
        string text;
        try
        {
            text = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        }
        catch (HttpRequestException e)
        {
            throw new McpTransportException("network error: " + e.GetType().Name);
        }
        var msgs = new List<JsonObject>();
        if (ct2.Contains("text/event-stream", StringComparison.OrdinalIgnoreCase))
        {
            foreach (var s in SseParser.ParseAll(text))
            {
                try
                {
                    if (JsonNode.Parse(s) is JsonObject o)
                    {
                        msgs.Add(o);
                    }
                }
                catch (JsonException)
                {
                    // skip
                }
            }
        }
        else
        {
            try
            {
                var node = JsonNode.Parse(text);
                if (node is JsonArray arr)
                {
                    msgs.AddRange(arr.OfType<JsonObject>());
                }
                else if (node is JsonObject o)
                {
                    msgs.Add(o);
                }
            }
            catch (JsonException)
            {
                throw new McpTransportException(
                    $"server returned a non-JSON body (HTTP {(int)resp.StatusCode})", (int)resp.StatusCode);
            }
        }
        JsonObject? chosen = null;
        foreach (var m in msgs)
        {
            if (m.ContainsKey("result") || m.ContainsKey("error"))
            {
                if (m["id"] is JsonValue iv && iv.TryGetValue<long>(out var mid) && mid == id)
                {
                    chosen = m;
                    break;
                }
                chosen ??= m;
            }
        }
        if (chosen is null)
        {
            throw new McpProtocolException("no JSON-RPC response in server reply");
        }
        if (chosen["error"] is JsonObject err)
        {
            int? code = err["code"] is JsonValue cv && cv.TryGetValue<int>(out var ci) ? ci : null;
            throw new McpProtocolException((string?)err["message"] ?? "protocol error", code);
        }
        if (chosen["result"] is JsonObject result)
        {
            return result;
        }
        throw new McpProtocolException("response has neither result nor error");
    }

    private async Task<HttpResponseMessage> SendAsync(JsonObject body, bool retry, CancellationToken ct)
    {
        var payload = body.ToJsonString();
        var attempt = 0;
        while (true)
        {
            HttpResponseMessage? resp = null;
            string? netErr = null;
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Post, Url())
                {
                    Content = new StringContent(payload, Encoding.UTF8, "application/json"),
                };
                ApplyHeaders(req, false);
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(_o.Timeout);
                // Buffer the body inside the timeout window, then return.
                resp = await _http.SendAsync(req, HttpCompletionOption.ResponseContentRead, cts.Token).ConfigureAwait(false);
            }
            catch (HttpRequestException e)
            {
                netErr = "network error: " + (e.InnerException?.GetType().Name ?? e.GetType().Name);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                netErr = $"request timed out after {(int)_o.Timeout.TotalSeconds}s";
            }
            if (resp is not null)
            {
                var s = (int)resp.StatusCode;
                var retryable = s == 429 || (retry && s >= 500 && s != 501);
                if (!retryable || attempt >= _o.MaxRetries)
                {
                    return resp;
                }
                var hint = RetryAfter(resp);
                resp.Dispose();
                await Task.Delay(Delay(attempt, hint), ct).ConfigureAwait(false);
            }
            else
            {
                if (!retry || attempt >= _o.MaxRetries)
                {
                    throw new McpTransportException(netErr ?? "network error");
                }
                await Task.Delay(Delay(attempt, null), ct).ConfigureAwait(false);
            }
            attempt++;
        }
    }

    private TimeSpan Delay(int attempt, TimeSpan? hint)
    {
        if (hint is { } h)
        {
            return h > TimeSpan.FromSeconds(30) ? TimeSpan.FromSeconds(30) : h;
        }
        var ms = _o.BackoffBase.TotalMilliseconds * (1 << Math.Min(attempt, 10));
        var jitter = Random.Shared.NextDouble() * ms / 4;
        return TimeSpan.FromMilliseconds(Math.Min(ms + jitter, 20000));
    }

    private static TimeSpan? RetryAfter(HttpResponseMessage resp)
    {
        var d = resp.Headers.RetryAfter?.Delta;
        return d;
    }

    private static async Task<McpException> StatusErrorAsync(HttpResponseMessage resp)
    {
        var status = (int)resp.StatusCode;
        var body = "";
        try
        {
            body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
        }
        catch (HttpRequestException)
        {
            // keep empty
        }
        var detail = body.Length > 300 ? body[..300] : body;
        try
        {
            if (JsonNode.Parse(body) is JsonObject j)
            {
                var e = j["error"] ?? j["message"];
                if (e is JsonValue ev && ev.TryGetValue<string>(out var es))
                {
                    detail = es;
                }
                else if (e is JsonObject eo && eo["message"] is JsonValue mv && mv.TryGetValue<string>(out var ms))
                {
                    detail = ms;
                }
            }
        }
        catch (JsonException)
        {
            // keep raw detail
        }
        return status switch
        {
            (int)HttpStatusCode.Unauthorized or (int)HttpStatusCode.Forbidden =>
                new McpAuthException($"authentication failed (HTTP {status}): {detail}", status),
            429 => new McpRateLimitException($"rate limited (HTTP 429): {detail}", RetryAfter(resp)),
            _ => new McpTransportException($"HTTP {status}: {detail}", status),
        };
    }

    internal static void Put(JsonObject o, string key, object? value)
    {
        if (value is null)
        {
            return;
        }
        o[key] = JsonSerializer.SerializeToNode(value, value.GetType());
    }
}
