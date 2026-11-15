using System.Text.RegularExpressions;
using Crm.Domain.Common;

namespace Crm.Domain.Collaboration;

/// <summary>Metadata of a file attached to a chat message (stored as JSON with the message).</summary>
public sealed record ChatAttachment
{
    public string FileName { get; set; } = string.Empty;
    public string StoredName { get; set; } = string.Empty;
    public string ContentType { get; set; } = "application/octet-stream";
    public long Size { get; set; }
}

/// <summary>
/// A message of the contextual "chatter" bound to any trackable entity.
/// Markup: <c>@username</c> mentions a user, <c>#[Type:Guid|Label]</c> links another object.
/// </summary>
public partial class ChatMessage : AuditableEntity
{
    public TrackableEntityType EntityType { get; set; }
    public Guid EntityId { get; set; }
    public Guid AuthorId { get; set; }
    public string AuthorName { get; set; } = string.Empty;
    public string Body { get; set; } = string.Empty;

    /// <summary>Set for thread replies; always points at a top-level message.</summary>
    public Guid? ParentMessageId { get; set; }
    public ChatMessage? ParentMessage { get; set; }
    public ICollection<ChatMessage> Replies { get; } = [];

    public List<Guid> MentionedUserIds { get; set; } = [];
    public List<ChatAttachment> Attachments { get; set; } = [];

    public EntityRef Entity => new(EntityType, EntityId);

    /// <summary>Extracts the distinct user names mentioned with <c>@name</c>.</summary>
    public static IReadOnlyList<string> ExtractMentions(string? body) =>
        body is null
            ? []
            : MentionPattern().Matches(body).Select(m => m.Groups[1].Value).Distinct(StringComparer.OrdinalIgnoreCase).ToList();

    /// <summary>Extracts the objects linked with <c>#[Type:Guid|Label]</c>.</summary>
    public static IReadOnlyList<EntityRef> ExtractLinks(string? body)
    {
        if (body is null)
        {
            return [];
        }

        var links = new List<EntityRef>();
        foreach (Match match in LinkPattern().Matches(body))
        {
            if (EntityRef.TryParse($"{match.Groups[1].Value}:{match.Groups[2].Value}", out var reference))
            {
                links.Add(reference);
            }
        }

        return links.Distinct().ToList();
    }

    [GeneratedRegex(@"(?<![\w@])@([A-Za-z0-9._-]{2,64})")]
    public static partial Regex MentionPattern();

    [GeneratedRegex(@"#\[(\w+):([0-9a-fA-F-]{36})\|([^\]]{1,200})\]")]
    public static partial Regex LinkPattern();
}
