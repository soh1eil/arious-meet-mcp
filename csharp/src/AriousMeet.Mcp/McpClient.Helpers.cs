using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;

namespace AriousMeet.Mcp;

public sealed partial class McpClient
{
    /// <summary>
    /// Long-polls <c>get_updates</c> forever and yields each update. The cursor is
    /// acknowledged (<c>ack_updates</c>) only after the consumer has finished a whole
    /// batch (when it asks for the next element), so a crash mid-batch re-delivers
    /// instead of losing items. Rate limits and transient failures back off and
    /// continue; authentication errors end the stream with the error.
    /// </summary>
    public async IAsyncEnumerable<JsonObject> WatchUpdatesAsync(
        IReadOnlyList<string>? only = null,
        int waitSeconds = 25,
        TimeSpan? idleBackoff = null,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var backoff = idleBackoff ?? TimeSpan.FromSeconds(2);
        string? cursor = null;
        var failures = 0;
        while (!ct.IsCancellationRequested)
        {
            ToolResult r;
            try
            {
                r = await GetUpdatesAsync(cursor: cursor, only: only, waitSeconds: waitSeconds, ct: ct).ConfigureAwait(false);
                failures = 0;
            }
            catch (McpRateLimitException e)
            {
                await Task.Delay(e.RetryAfter ?? backoff, ct).ConfigureAwait(false);
                continue;
            }
            catch (McpTransportException)
            {
                failures++;
                await Task.Delay(backoff * Math.Min(failures, 5), ct).ConfigureAwait(false);
                continue;
            }
            var data = r.Data as JsonObject;
            var updates = (data?["updates"] as JsonArray)?.OfType<JsonObject>().ToList() ?? [];
            var next = (string?)data?["next_cursor"];
            foreach (var u in updates)
            {
                yield return (JsonObject)u.DeepClone();
            }
            if (!string.IsNullOrEmpty(next))
            {
                if (updates.Count > 0)
                {
                    await AckUpdatesAsync(next, ct).ConfigureAwait(false);
                }
                cursor = next;
            }
        }
    }

    /// <summary>
    /// Stages <paramref name="bytes"/> with <c>create_upload_url</c>, PUTs them, and returns
    /// the <c>upload_id</c> (for <c>send_message</c> attachment_ids or <c>send_file</c>).
    /// </summary>
    public async Task<string> UploadBytesAsync(
        string conversationId,
        string filename,
        byte[] bytes,
        string? mime = null,
        CancellationToken ct = default)
    {
        var t = await CreateUploadUrlAsync(conversationId, filename, bytes.Length, mime, ct).ConfigureAwait(false);
        var d = t.Structured;
        var url = (string?)d?["upload_url"];
        var id = (string?)d?["upload_id"];
        if (url is null || id is null)
        {
            throw new McpProtocolException("create_upload_url returned no upload_url/upload_id");
        }
        var headers = new Dictionary<string, string>();
        if (d?["headers"] is JsonObject h)
        {
            foreach (var kv in h)
            {
                if ((string?)kv.Value is { } v)
                {
                    headers[kv.Key] = v;
                }
            }
        }
        await PutBytesAsync(url, bytes, headers, ct).ConfigureAwait(false);
        return id;
    }

    /// <summary>Uploads a local file and sends it as its own message.</summary>
    public async Task<ToolResult> SendLocalFileAsync(
        string conversationId,
        string path,
        string? caption = null,
        string? mime = null,
        CancellationToken ct = default)
    {
        var bytes = await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false);
        var id = await UploadBytesAsync(conversationId, Path.GetFileName(path), bytes, mime, ct).ConfigureAwait(false);
        return await SendFileAsync(conversationId, id, caption: caption, ct: ct).ConfigureAwait(false);
    }
}
