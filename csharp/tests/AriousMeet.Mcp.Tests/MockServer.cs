using System.Diagnostics;
using System.Text;
using System.Text.Json.Nodes;

namespace AriousMeet.Mcp.Tests;

/// <summary>Starts the shared Python mock (../mock/server.py) on a free port.</summary>
public sealed class MockServer : IDisposable
{
    private static long _n;
    private readonly Process _proc;
    private static readonly HttpClient Http = new();

    public string Url { get; }
    public string Origin => Url.Replace("/v1/mcp", "", StringComparison.Ordinal);

    private MockServer(Process p, string url)
    {
        _proc = p;
        Url = url;
    }

    public static string UniqueToken() => $"test-dotnet-{DateTime.UtcNow.Ticks}-{Interlocked.Increment(ref _n)}";

    private static string FindScript()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var f = Path.Combine(dir.FullName, "mock", "server.py");
            if (File.Exists(f))
            {
                return f;
            }
            dir = dir.Parent;
        }
        throw new FileNotFoundException("mock/server.py not found above " + AppContext.BaseDirectory);
    }

    public static MockServer Start(string mode = "json")
    {
        var psi = new ProcessStartInfo("python3")
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        foreach (var a in new[] { FindScript(), "--port", "0", "--mode", mode, "--fail-count", "2" })
        {
            psi.ArgumentList.Add(a);
        }
        var p = Process.Start(psi) ?? throw new InvalidOperationException("cannot start python3");
        var line = p.StandardOutput.ReadLine() ?? throw new InvalidOperationException("mock gave no banner");
        _ = p.StandardOutput.ReadToEndAsync();
        _ = p.StandardError.ReadToEndAsync();
        return new MockServer(p, line.Replace("LISTENING ", "", StringComparison.Ordinal).Trim());
    }

    public McpClient Client(string? token = null, string? model = "Test Model", int maxRetries = 3, bool tokenInPath = false) =>
        new(new McpClientOptions
        {
            Token = token ?? UniqueToken(),
            BaseUrl = Url,
            ModelName = model,
            MaxRetries = maxRetries,
            TokenInPath = tokenInPath,
            BackoffBase = TimeSpan.FromMilliseconds(5),
            Timeout = TimeSpan.FromSeconds(15),
        });

    public async Task<JsonArray> LogAsync()
    {
        var s = await Http.GetStringAsync(Origin + "/__mock/log");
        return (JsonArray)JsonNode.Parse(s)!["log"]!;
    }

    public async Task<IReadOnlyList<(string Conversation, string Action)>> ActionsAsync()
    {
        var s = await Http.GetStringAsync(Origin + "/__mock/log");
        var arr = (JsonArray)JsonNode.Parse(s)!["actions"]!;
        return arr.Select(a => ((string)a!["conversation_id"]!, (string)a!["action"]!)).ToList();
    }

    public async Task ControlAsync(string path, string json)
    {
        using var r = await Http.PostAsync(Origin + path, new StringContent(json, Encoding.UTF8, "application/json"));
        r.EnsureSuccessStatusCode();
    }

    public async Task PushAsync(string token, string itemsJson)
    {
        var body = $"{{\"token\":\"{token}\",\"items\":{itemsJson}}}";
        using var r = await Http.PostAsync(Origin + "/__mock/push", new StringContent(body, Encoding.UTF8, "application/json"));
        r.EnsureSuccessStatusCode();
    }

    public void Dispose()
    {
        try
        {
            _proc.Kill();
            _proc.WaitForExit();
        }
        catch (InvalidOperationException)
        {
            // already gone
        }
        _proc.Dispose();
    }
}
