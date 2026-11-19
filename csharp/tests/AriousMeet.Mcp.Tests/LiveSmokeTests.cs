namespace AriousMeet.Mcp.Tests;

/// <summary>
/// LIVE smoke test. Read-only calls ONLY: the handshake, prompts/list, whoami, start_here and context_list.
/// Never add SendMessage, GetUpdates, ReadMessages, MarkRead, AckUpdates or ContextCheckpoint here.
/// Does nothing unless ARIOUS_MCP_TOKEN is set.
/// </summary>
public class LiveSmokeTests
{
    [Fact]
    public async Task LiveReadOnlyTools()
    {
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("ARIOUS_MCP_TOKEN")))
        {
            return;
        }
        using var c = McpClient.FromEnvironment();
        await c.InitializeAsync();
        Assert.NotEmpty(await c.ListToolsAsync());
        Assert.Contains(await c.ListPromptsAsync(), p => p.Name == "resume");
        Assert.False((await c.WhoamiAsync()).IsError);
        var start = StartHere.From(await c.StartHereAsync());
        Assert.NotEmpty(start.AgentId);
        Assert.NotEmpty(start.DoNow);
        try
        {
            Assert.NotNull((await c.ContextListAsync()).Structured?["contexts"]);
        }
        catch (McpToolException e)
        {
            // the owner may have switched Arious Context off
            Assert.False((bool)e.Result!.Structured!["contexts_enabled"]!);
        }
    }
}
