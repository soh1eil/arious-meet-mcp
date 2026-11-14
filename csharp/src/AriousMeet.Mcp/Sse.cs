using System.Text;

namespace AriousMeet.Mcp;

/// <summary>Incremental Server-Sent-Events parser.</summary>
public sealed class SseParser
{
    private readonly StringBuilder _pending = new();
    private readonly List<string> _data = [];

    /// <summary>Feed a chunk of text; returns every <c>data:</c> payload it completed.</summary>
    public IReadOnlyList<string> Feed(string chunk)
    {
        _pending.Append(chunk);
        var all = _pending.ToString();
        var result = new List<string>();
        var start = 0;
        int i;
        while ((i = all.IndexOf('\n', start)) >= 0)
        {
            var line = all[start..i];
            start = i + 1;
            if (line.EndsWith('\r'))
            {
                line = line[..^1];
            }
            if (line.Length == 0)
            {
                if (_data.Count > 0)
                {
                    result.Add(string.Join('\n', _data));
                    _data.Clear();
                }
            }
            else if (line.StartsWith("data:", StringComparison.Ordinal))
            {
                var v = line[5..];
                _data.Add(v.StartsWith(' ') ? v[1..] : v);
            }
        }
        _pending.Clear().Append(all[start..]);
        return result;
    }

    /// <summary>Flush a trailing event that had no closing blank line.</summary>
    public IReadOnlyList<string> Finish()
    {
        var r = new List<string>(Feed("\n"));
        r.AddRange(Feed("\n"));
        return r;
    }

    /// <summary>Parse a complete SSE body into its data payloads.</summary>
    public static IReadOnlyList<string> ParseAll(string body)
    {
        var p = new SseParser();
        var r = new List<string>(p.Feed(body));
        r.AddRange(p.Finish());
        return r;
    }
}
