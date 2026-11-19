using System.Text.Json;
using System.Text.Json.Nodes;

namespace AriousMeet.Mcp;

/// <summary>Schema facts the client needs per tool (generated).</summary>
public readonly record struct ToolTraits(
    bool HasModelName,
    bool RequiresModelName,
    bool HasClientMessageId,
    bool SafeToRepeat);

/// <summary>Decoded result of <c>tools/call</c>.</summary>
public sealed class ToolResult
{
    public ToolResult(string text, JsonArray content, JsonObject? structured, bool isError)
    {
        Text = text;
        Content = content;
        Structured = structured;
        IsError = isError;
    }

    /// <summary>First text block.</summary>
    public string Text { get; }

    /// <summary>Every content block as sent by the server.</summary>
    public JsonArray Content { get; }

    /// <summary><c>structuredContent</c>, when the tool provides it.</summary>
    public JsonObject? Structured { get; }

    public bool IsError { get; }

    /// <summary>Structured content if present, else the text parsed as JSON, else the text.</summary>
    public JsonNode? Data
    {
        get
        {
            if (Structured is not null)
            {
                return Structured;
            }
            try
            {
                return JsonNode.Parse(Text);
            }
            catch (JsonException)
            {
                return JsonValue.Create(Text);
            }
        }
    }

    /// <summary>
    /// The one-line reminder the server adds to <c>get_updates</c>, <c>read_messages</c> and <c>get_message</c>
    /// while Arious Context is on for this agent; null otherwise.
    /// </summary>
    public string? ContextReminder => Structured?["context_reminder"] is JsonValue v && v.TryGetValue<string>(out var s) && s.Length > 0 ? s : null;

    /// <summary>The <c>platform_update</c> items of a <c>get_updates</c> result.</summary>
    public IReadOnlyList<PlatformUpdate> PlatformUpdates =>
        (Structured?["updates"] as JsonArray)?.OfType<JsonObject>()
            .Where(u => (string?)u["kind"] == "platform_update")
            .Select(PlatformUpdate.From)
            .ToList() ?? [];
}
