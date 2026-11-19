using System.Text.Json.Nodes;

namespace AriousMeet.Mcp.Tests;

/// <summary>Arious Context, start_here, prompts and platform updates against the shared mock.</summary>
public class ContextTests
{
    private static JsonObject D(ToolResult r) => (JsonObject)r.Data!;

    private static async Task<string> CreateAsync(McpClient c, string title, string goal) =>
        (string)D(await c.ContextCreateAsync(title, goal: goal))["context"]!["id"]!;

    private static JsonObject Append(params (string Key, string Value)[] steps)
    {
        var a = new JsonObject();
        foreach (var (k, v) in steps)
        {
            a[k] = new JsonArray(v);
        }
        return a;
    }

    [Theory]
    [InlineData("json")]
    [InlineData("sse")]
    public async Task ResumeWhereAnotherAgentLeftOff(string mode)
    {
        using var m = MockServer.Start(mode);
        var token = MockServer.UniqueToken();
        using var writer = m.Client(token, "Agent A");
        using var reader = m.Client(token, "Agent B");
        var cid = await CreateAsync(writer, "Ship 0.3", "Release the SDK");
        var first = CheckpointResult.From(await writer.ContextCheckpointAsync(
            1, cid, currentStep: "Writing tests",
            append: Append(("done_steps", "Spec read"), ("next_steps", "Run the suite"))));
        Assert.Equal(2, first.Version);
        Assert.False(first.Conflict);
        Assert.False(first.WasRedacted);

        var resume = ContextResume.From(await reader.ContextResumeAsync()); // newest active context
        Assert.Equal(cid, resume.ContextId);
        Assert.Equal(2, resume.Version);
        Assert.True(resume.CanWrite);
        Assert.Equal("personal", resume.Scope);
        Assert.Null(resume.OrganizationId);
        Assert.Contains("Where we are now: Writing tests", resume.Brief, StringComparison.Ordinal);
        Assert.Contains("Next step: Run the suite", resume.Brief, StringComparison.Ordinal);
        var next = CheckpointResult.From(await reader.ContextCheckpointAsync(
            resume.Version, cid, append: Append(("done_steps", "Suite green"))));
        Assert.Equal(3, next.Version);
        var got = D(await reader.ContextGetAsync(cid, history: 2));
        var v = ContextVersion.From(got["version"]!);
        Assert.Equal("Agent B", v.Author.Model);
        Assert.Equal(new[] { "Spec read", "Suite green" }, v.DoneSteps);
        Assert.Equal(new[] { 3, 2 }, ((JsonArray)got["history"]!).Select(h => (int)h!["version"]!).ToArray());
    }

    [Fact]
    public async Task CheckpointRedactsSecretsAndReportsThem()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var cid = await CreateAsync(c, "T", "g");
        var res = CheckpointResult.From(await c.ContextCheckpointAsync(
            1, cid, notes: "use sk-abcdefghijklmnopqrstuvwxyz and password=hunter2 here"));
        Assert.True(res.WasRedacted);
        Assert.Equal(2, res.Redacted.Count);
        Assert.Contains(new Redaction("notes", "api_key", 1), res.Redacted);
        Assert.Contains(new Redaction("notes", "secret_value", 1), res.Redacted);
        var notes = (string)D(await c.ContextGetAsync(cid))["version"]!["notes"]!;
        Assert.DoesNotContain("hunter2", notes, StringComparison.Ordinal);
        Assert.Contains("[REDACTED:api_key]", notes, StringComparison.Ordinal);
    }

    [Fact]
    public async Task LostRaceThrowsContextConflictWithLatest()
    {
        using var m = MockServer.Start();
        var token = MockServer.UniqueToken();
        using var c = m.Client(token);
        var cid = await CreateAsync(c, "T", "g");
        await m.ControlAsync("/__mock/context_write",
            $"{{\"token\":\"{token}\",\"context_id\":\"{cid}\",\"current_step\":\"elsewhere\",\"model\":\"Other\"}}");
        var e = await Assert.ThrowsAsync<ContextConflictException>(
            () => c.ContextCheckpointAsync(1, cid, currentStep: "mine"));
        Assert.IsAssignableFrom<McpToolException>(e); // old handlers keep working
        Assert.Equal("context_checkpoint", e.Tool);
        Assert.Equal(1, e.BaseVersion);
        Assert.Equal(2, e.LatestVersion);
        Assert.Equal("elsewhere", e.Latest?.CurrentStep);
        Assert.Equal("Other", e.Latest?.Author.Model);
        Assert.True(e.Result?.IsError);
        var ok = CheckpointResult.From(await c.ContextCheckpointAsync(e.LatestVersion, cid, currentStep: "mine"));
        Assert.Equal(3, ok.Version);
    }

    [Fact]
    public async Task ConflictAsAResultWithThrowOnErrorFalse()
    {
        using var m = MockServer.Start();
        var token = MockServer.UniqueToken();
        using var c = m.Client(token);
        var cid = await CreateAsync(c, "T", "g");
        await m.ControlAsync("/__mock/context_write", $"{{\"token\":\"{token}\",\"context_id\":\"{cid}\"}}");
        var raw = await c.CallToolAsync(
            "context_checkpoint",
            new JsonObject { ["context_id"] = cid, ["base_version"] = 1, ["notes"] = "x" },
            throwOnError: false);
        Assert.True(raw.IsError);
        var res = CheckpointResult.From(raw);
        Assert.True(res.Conflict);
        Assert.Equal(1, res.BaseVersion);
        Assert.Equal(2, res.LatestVersion);
        Assert.Equal(2, res.Latest?.Version);
    }

    [Fact]
    public async Task OtherToolErrorsStayPlainToolExceptions()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var e = await Assert.ThrowsAsync<McpToolException>(() => c.ContextGetAsync("nope"));
        Assert.IsNotType<ContextConflictException>(e);
        Assert.Contains("not found", e.Message, StringComparison.Ordinal);
        var e2 = await Assert.ThrowsAsync<McpToolException>(() => c.ContextResumeAsync());
        Assert.Contains("no active context", e2.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ListSearchStatusAndValidation()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var a = await CreateAsync(c, "Alpha plan", "first goal");
        var b = await CreateAsync(c, "Beta plan", "second goal");
        static string[] Ids(ToolResult r) => ((JsonArray)D(r)["contexts"]!).Select(x => (string)x!["id"]!).ToArray();
        Assert.Equal(new[] { a, b }.Order(), Ids(await c.ContextListAsync()).Order());
        await c.ContextSetStatusAsync(a, "paused");
        Assert.Equal(new[] { a }, Ids(await c.ContextListAsync(status: "paused")));
        Assert.Equal(new[] { b }, Ids(await c.ContextSearchAsync("second")));
        await Assert.ThrowsAsync<McpToolException>(() => c.ContextCheckpointAsync(-1, a));
        await Assert.ThrowsAsync<McpToolException>(() => c.ContextSetStatusAsync(a, "archived"));
    }

    [Fact]
    public async Task ContextOffIsAToolErrorWithTheReason()
    {
        using var m = MockServer.Start();
        var token = MockServer.UniqueToken();
        using var c = m.Client(token);
        await m.ControlAsync("/__mock/contexts", $"{{\"token\":\"{token}\",\"enabled\":false}}");
        var e = await Assert.ThrowsAsync<McpToolException>(() => c.ContextListAsync());
        Assert.False((bool)e.Result!.Structured!["contexts_enabled"]!);
        Assert.Equal("turned_off_by_owner", (string)e.Result.Structured["reason"]!);
        Assert.False(StartHere.From(await c.StartHereAsync()).ContextsEnabled);
        await m.ControlAsync("/__mock/contexts", $"{{\"token\":\"{token}\",\"enabled\":true}}");
        Assert.Empty((JsonArray)D(await c.ContextListAsync())["contexts"]!);
    }

    [Fact]
    public async Task OrganizationScopeAndClassification()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var personal = await CreateAsync(c, "Mine", "g");
        var org = D(await c.ContextCreateAsync(
            "Board pack", goal: "g", organizationId: "org-1", classification: "confidential"));
        var oc = org["context"]!;
        Assert.Equal("organization", (string)oc["scope"]!);
        Assert.Equal("confidential", (string)oc["classification"]!);
        var mine = (JsonArray)D(await c.ContextListAsync())["contexts"]!;
        Assert.Equal(personal, (string)Assert.Single(mine)!["id"]!);
        var listed = D(await c.ContextListAsync(organizationId: "org-1"));
        Assert.Equal("organization", (string)listed["scope"]!);
        Assert.Equal((string)oc["id"]!, (string)((JsonArray)listed["contexts"]!)[0]!["id"]!);
        var res = ContextResume.From(await c.ContextResumeAsync(
            contextId: (string)oc["id"]!, organizationId: "org-1", conversationId: "conv-1"));
        Assert.Equal("organization", res.Scope);
        Assert.Equal("org-1", res.OrganizationId);
        Assert.Equal("confidential", res.Classification);
        var e = await Assert.ThrowsAsync<McpToolException>(
            () => c.ContextCreateAsync("S", organizationId: "org-1", classification: "secret"));
        Assert.Contains("clearance", e.Message, StringComparison.Ordinal);
        var e2 = await Assert.ThrowsAsync<McpToolException>(() => c.ContextListAsync(organizationId: "org-9"));
        Assert.Contains("organization not found", e2.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task StartHereIsTypedAndPlatformUpdatesAreAckedById()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var cid = await CreateAsync(c, "Resume me", "goal");
        var s = StartHere.From(await c.StartHereAsync());
        Assert.Equal("Mock Agent", s.Name);
        Assert.True(s.ContextsEnabled);
        Assert.Equal(cid, s.LastContextId);
        Assert.Contains("Resume me", s.LastContextBrief, StringComparison.Ordinal);
        Assert.Equal(2, s.UnreadUpdates);
        Assert.Equal(new[] { "upd-context" }, s.ImportantUpdateIds);
        Assert.Equal("conv-1", s.Conversations[0].Id);
        Assert.NotEmpty(s.HouseRules);
        Assert.NotEmpty(s.DoNow);
        Assert.StartsWith("START HERE", s.Text, StringComparison.Ordinal);
        await c.AckUpdatesAsync(updateIds: s.ImportantUpdateIds);
        Assert.Empty(StartHere.From(await c.StartHereAsync()).ImportantUpdateIds);
        await Assert.ThrowsAsync<McpToolException>(() => c.AckUpdatesAsync());
    }

    [Fact]
    public async Task PromptsListAndGet()
    {
        using var m = MockServer.Start();
        using var c = m.Client();
        var prompts = await c.ListPromptsAsync();
        Assert.Equal(new[] { "start", "resume" }, prompts.Select(p => p.Name));
        Assert.Empty(prompts[0].Arguments);
        Assert.Equal(
            new[] { ("context_id", false), ("organization_id", false) },
            prompts[1].Arguments.Select(a => (a.Name, a.Required)));
        var cid = await CreateAsync(c, "Prompted", "g");
        var res = await c.GetPromptAsync("resume", new Dictionary<string, string> { ["context_id"] = cid });
        Assert.Equal("user", Assert.Single(res.Messages).Role);
        Assert.Contains("Title: Prompted", res.Text, StringComparison.Ordinal);
        Assert.Contains("START HERE", (await c.GetPromptAsync("start")).Text, StringComparison.Ordinal);
        var e = await Assert.ThrowsAsync<McpProtocolException>(() => c.GetPromptAsync("nope"));
        Assert.Equal(-32602, e.Code);
    }

    [Fact]
    public async Task ContextReminderAndPlatformUpdateItems()
    {
        using var m = MockServer.Start();
        var token = MockServer.UniqueToken();
        using var c = m.Client(token);
        await m.PushAsync(token,
            "[{\"kind\":\"message\",\"conversation_id\":\"c1\",\"message_id\":\"m1\",\"text\":\"hi\"},"
            + "{\"kind\":\"platform_update\",\"id\":\"upd-x\",\"title\":\"New\",\"importance\":\"important\"}]");
        var res = await c.GetUpdatesAsync();
        Assert.Contains("context_checkpoint", res.ContextReminder, StringComparison.Ordinal);
        var pu = Assert.Single(res.PlatformUpdates);
        Assert.Equal("upd-x", pu.Id);
        Assert.True(pu.Important);
        Assert.NotNull((await c.ReadMessagesAsync("c1")).ContextReminder);
        Assert.NotNull((await c.GetMessageAsync("c1", "m1")).ContextReminder);
        Assert.Null((await c.ReadMessagesAsync("empty")).ContextReminder);
        await m.ControlAsync("/__mock/contexts", $"{{\"token\":\"{token}\",\"enabled\":false}}");
        Assert.Null((await c.GetUpdatesAsync()).ContextReminder);
    }
}
