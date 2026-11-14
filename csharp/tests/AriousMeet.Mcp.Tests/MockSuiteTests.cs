using System.Text;
using System.Text.Json.Nodes;

namespace AriousMeet.Mcp.Tests;

public class MockSuiteTests
{
    [Theory]
    [InlineData("json")]
    [InlineData("sse")]
    public async Task HandshakeListsAll124Tools(string mode)
    {
        using var m = MockServer.Start(mode);
        using var c = m.Client();
        var info = await c.InitializeAsync();
        Assert.NotNull(info["serverInfo"]);
        var tools = await c.ListToolsAsync();
        Assert.Equal(124, tools.Count);
        var names = tools.Select(t => (string)t["name"]!).ToHashSet();
        Assert.All(McpClient.ToolNames, n => Assert.Contains(n, names));
        Assert.Equal(124, McpClient.ToolNames.Count);
    }

    [Theory]
    [InlineData("json")]
    [InlineData("sse")]
    public async Task ReadOnlyTools(string mode)
    {
        using var m = MockServer.Start(mode);
        using var c = m.Client();
        Assert.Equal("Mock Agent", (string?)c_Data(await c.WhoamiAsync())["display_name"]);
        var h = await c.GetHandbookAsync("tasks");
        Assert.Null(h.Structured);
        Assert.Contains("tasks", h.Text, StringComparison.Ordinal);
        var g = await c.SearchAppGuideAsync("calls");
        Assert.NotEmpty((JsonArray)c_Data(g)["results"]!);
        var o = await c.ListOrganizationsAsync();
        Assert.NotEmpty((JsonArray)c_Data(o)["organizations"]!);
    }

    private static JsonObject c_Data(ToolResult r) => (JsonObject)r.Data!;

    [Fact]
    public async Task BadTokenIsAuthErrorWithoutLeak()
    {
        using var m = MockServer.Start();
        using var c = m.Client("wrong-secret-token");
        var e = await Assert.ThrowsAsync<McpAuthException>(() => c.WhoamiAsync());
        Assert.Equal(401, e.Status);
        Assert.DoesNotContain("wrong-secret-token", e.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("wrong-secret-token", c.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task ToolAndProtocolErrors()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var te = await Assert.ThrowsAsync<McpToolException>(() => c.CallToolAsync("mock_tool_error"));
        Assert.Contains("tool-level", te.Message, StringComparison.Ordinal);
        var raw = await c.CallToolAsync("mock_tool_error", null, false);
        Assert.True(raw.IsError);
        var pe = await Assert.ThrowsAsync<McpProtocolException>(() => c.CallToolAsync("mock_protocol_error"));
        Assert.Equal(-32602, pe.Code);
        await Assert.ThrowsAsync<McpProtocolException>(() => c.CallToolAsync("no_such_tool_at_all"));
    }

    [Fact]
    public async Task LocalArgumentChecks()
    {
        Assert.Throws<ArgumentException>(() => new McpClient(new McpClientOptions { Token = "  " }));
        using var m = MockServer.Start();
        using var c = m.Client(model: null);
        await Assert.ThrowsAsync<ArgumentException>(() => c.SendMessageAsync("c1", "x"));
    }

    [Fact]
    public async Task NetworkErrorIsTransport()
    {
        using var c = new McpClient(new McpClientOptions
        {
            Token = "test-x",
            BaseUrl = "http://127.0.0.1:1/v1/mcp",
            MaxRetries = 1,
            BackoffBase = TimeSpan.FromMilliseconds(1),
        });
        await Assert.ThrowsAsync<McpTransportException>(() => c.WhoamiAsync());
    }

    [Fact]
    public async Task RateLimitRetriedThenSucceeds()
    {
        using var m = MockServer.Start("ratelimit");
        using var c = m.Client();
        Assert.False((await c.WhoamiAsync()).IsError);
        var n = (await m.LogAsync()).Count(e => e!.ToJsonString().Contains("whoami", StringComparison.Ordinal));
        Assert.True(n >= 3, $"expected 2 rejected + 1 accepted, saw {n}");
    }

    [Fact]
    public async Task RateLimitExhausted()
    {
        using var m = MockServer.Start("ratelimit");
        using var c = m.Client(maxRetries: 1);
        await Assert.ThrowsAsync<McpRateLimitException>(() => c.WhoamiAsync());
    }

    [Fact]
    public async Task Http500RetryRules()
    {
        using var m = MockServer.Start("error");
        using (var c = m.Client())
        {
            Assert.False((await c.WhoamiAsync()).IsError); // read-only: retried
        }
        using (var c = m.Client())
        {
            var r = await c.SendMessageAsync("c1", "hello"); // gets client_message_id: retried
            Assert.Contains("Test Model", (string)r.Data!["text"]!, StringComparison.Ordinal);
        }

        // A non-idempotent tool with no message id is NOT retried.
        using var m2 = MockServer.Start("error");
        using var c2 = m2.Client();
        var ex = await Assert.ThrowsAsync<McpTransportException>(() => c2.CallToolAsync(NonIdempotentTool()));
        Assert.Equal(500, ex.Status);
        var calls = (await m2.LogAsync()).Count(e => e!.ToJsonString().Contains("tools/call", StringComparison.Ordinal));
        Assert.Equal(1, calls);
    }

    private static string NonIdempotentTool()
    {
        var spec = JsonNode.Parse(File.ReadAllText(FindSpec()))!["tools"]!.AsArray();
        foreach (var t in spec)
        {
            var a = t!["annotations"]!;
            var props = t["inputSchema"]!["properties"]!.AsObject();
            var safe = (bool?)a["readOnlyHint"] == true || (bool?)a["idempotentHint"] == true;
            if (!safe && !props.ContainsKey("client_message_id") && !props.ContainsKey("model_name"))
            {
                return (string)t["name"]!;
            }
        }
        throw new InvalidOperationException("no such tool");
    }

    private static string FindSpec()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var f = Path.Combine(dir.FullName, "spec", "tools.json");
            if (File.Exists(f))
            {
                return f;
            }
            dir = dir.Parent;
        }
        throw new FileNotFoundException("spec/tools.json");
    }

    [Fact]
    public async Task SendMessageSignsAndDedupes()
    {
        using var m = MockServer.Start();
        using var c = m.Client(model: "Claude Test");
        var a = c_Data(await c.SendMessageAsync("c1", "hi", clientMessageId: "abc-1"));
        var b = c_Data(await c.SendMessageAsync("c1", "hi", clientMessageId: "abc-1"));
        Assert.Equal((string?)a["message_id"], (string?)b["message_id"]);
        Assert.True((bool?)b["deduplicated"]);
        Assert.EndsWith("Claude Test", (string)a["text"]!, StringComparison.Ordinal);
        var e = c_Data(await c.SendMessageAsync("c1", "hi", modelName: "Explicit"));
        Assert.EndsWith("Explicit", (string)e["text"]!, StringComparison.Ordinal);
    }

    [Fact]
    public async Task WatchUpdatesYieldsAndAcks()
    {
        using var m = MockServer.Start();
        var tok = MockServer.UniqueToken();
        using var c = m.Client(tok, null);
        await m.PushAsync(tok, "[{\"kind\":\"mention\",\"conversation_id\":\"c1\",\"text\":\"one\"},{\"kind\":\"mention\",\"conversation_id\":\"c1\",\"text\":\"two\"}]");
        var got = new List<string>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        await foreach (var u in c.WatchUpdatesAsync(waitSeconds: 1, ct: cts.Token))
        {
            got.Add((string)u["text"]!);
            if (got.Count == 2)
            {
                break;
            }
        }
        Assert.Equal(["one", "two"], got);
    }

    [Fact]
    public async Task UploadBytesAndSendFile()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var id = await c.UploadBytesAsync("c1", "a.txt", Encoding.UTF8.GetBytes("hello"), "text/plain");
        var r = await c.SendFileAsync("c1", id);
        Assert.Equal(5, (int)c_Data(r)["size_bytes"]!);
    }

    [Fact]
    public async Task NotificationsStream()
    {
        using var m = MockServer.Start();
        var tok = MockServer.UniqueToken();
        using var c = m.Client(tok, null);
        await m.PushAsync(tok, "[{\"kind\":\"mention\",\"conversation_id\":\"c1\",\"text\":\"ping\"}]");
        var events = new List<JsonObject>();
        await foreach (var e in c.NotificationsAsync())
        {
            events.Add(e);
        }
        Assert.Equal("notifications/resources/updated", (string?)events[0]["method"]);
    }

    [Fact]
    public async Task TokenInPathForm()
    {
        using var m = MockServer.Start();
        using var c = m.Client(tokenInPath: true);
        Assert.False((await c.WhoamiAsync()).IsError);
    }

    [Fact]
    public void SseParserHandlesMultilineAndComments()
    {
        Assert.Equal(["a\nb", "c"], SseParser.ParseAll(": hi\n\ndata: a\ndata: b\n\ndata:c\n\n"));
        Assert.Equal(["tail"], SseParser.ParseAll("data: tail"));
    }
}
