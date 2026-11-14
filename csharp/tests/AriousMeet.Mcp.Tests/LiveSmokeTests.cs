namespace AriousMeet.Mcp.Tests;

/// <summary>
/// LIVE smoke test. Calls ONLY whoami, get_handbook, search_app_guide and
/// list_organizations. Does nothing unless ARIOUS_MCP_TOKEN is set.
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
        Assert.False((await c.WhoamiAsync()).IsError);
        Assert.NotEmpty((await c.GetHandbookAsync("formatting")).Text);
        Assert.False((await c.SearchAppGuideAsync("calls")).IsError);
        Assert.False((await c.ListOrganizationsAsync()).IsError);
    }
}
