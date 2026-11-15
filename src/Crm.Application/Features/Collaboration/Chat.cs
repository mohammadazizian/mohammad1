using Crm.Application.Common.Security;
using Crm.Domain.Collaboration;

namespace Crm.Application.Features.Collaboration;

public sealed record ChatMessageDto(
    Guid Id,
    Guid? ParentMessageId,
    Guid AuthorId,
    string AuthorName,
    string Body,
    DateTime CreatedAt,
    IReadOnlyList<ChatAttachment> Attachments,
    IReadOnlyList<ChatMessageDto> Replies);

public sealed record ChatThreadDto(TrackableInfo Entity, IReadOnlyList<ChatMessageDto> Messages)
{
    public int Count => Messages.Sum(m => 1 + m.Replies.Count);
}

/// <summary>The full conversation bound to one trackable entity (top-level messages with replies).</summary>
public sealed record GetChatThreadQuery(EntityRef Entity) : IRequest<ChatThreadDto>;

internal sealed class GetChatThreadQueryHandler(IApplicationDbContext db, ITrackableEntityResolver resolver)
    : IRequestHandler<GetChatThreadQuery, ChatThreadDto>
{
    public async Task<ChatThreadDto> Handle(GetChatThreadQuery request, CancellationToken cancellationToken)
    {
        var entity = await resolver.ResolveAsync(request.Entity, cancellationToken)
            ?? throw new NotFoundException(request.Entity.Type.ToString(), request.Entity.Id);

        var messages = await db.ChatMessages.AsNoTracking()
            .Where(m => m.EntityType == request.Entity.Type && m.EntityId == request.Entity.Id)
            .OrderBy(m => m.CreatedAt)
            .ToListAsync(cancellationToken);

        var replies = messages.Where(m => m.ParentMessageId is not null).ToLookup(m => m.ParentMessageId!.Value);
        var thread = messages
            .Where(m => m.ParentMessageId is null)
            .Select(m => m.ToDto(replies[m.Id].Select(r => r.ToDto([])).ToList()))
            .ToList();

        return new ChatThreadDto(entity, thread);
    }
}

public sealed record GetChatMessageQuery(Guid Id) : IRequest<ChatMessageDto>;

internal sealed class GetChatMessageQueryHandler(IApplicationDbContext db) : IRequestHandler<GetChatMessageQuery, ChatMessageDto>
{
    public async Task<ChatMessageDto> Handle(GetChatMessageQuery request, CancellationToken cancellationToken)
    {
        var message = await db.ChatMessages.AsNoTracking().FirstOrDefaultAsync(m => m.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(ChatMessage), request.Id);
        return message.ToDto([]);
    }
}

internal static class ChatMapping
{
    public static ChatMessageDto ToDto(this ChatMessage message, IReadOnlyList<ChatMessageDto> replies) => new(
        message.Id, message.ParentMessageId, message.AuthorId, message.AuthorName, message.Body,
        message.CreatedAt, message.Attachments, replies);
}

/// <summary>
/// Posts a message to an entity's chat. <c>@user</c> mentions raise real-time notifications
/// and every subscriber of the entity's chat receives the message through SignalR.
/// </summary>
public sealed record PostChatMessageCommand(
    EntityRef Entity,
    string? Body,
    Guid? ParentMessageId,
    IReadOnlyList<StoredFile> Attachments) : IRequest<Guid>;

internal sealed class PostChatMessageCommandValidator : AbstractValidator<PostChatMessageCommand>
{
    public const int MaxAttachments = 5;

    public PostChatMessageCommandValidator()
    {
        RuleFor(x => x.Body).MaximumLength(4000);
        RuleFor(x => x.Body).NotEmpty().When(x => x.Attachments.Count == 0);
        RuleFor(x => x.Attachments).Must(a => a.Count <= MaxAttachments)
            .WithMessage($"At most {MaxAttachments} files can be attached to a message.");
    }
}

internal sealed class PostChatMessageCommandHandler(
    IApplicationDbContext db,
    ICurrentUser currentUser,
    ITrackableEntityResolver resolver,
    IIdentityService identity,
    INotificationService notifications,
    IRealtimeNotifier realtime)
    : IRequestHandler<PostChatMessageCommand, Guid>
{
    private const int ExcerptLength = 140;

    public async Task<Guid> Handle(PostChatMessageCommand request, CancellationToken cancellationToken)
    {
        var authorId = currentUser.UserId ?? throw new ForbiddenAccessException();
        var entity = await resolver.ResolveAsync(request.Entity, cancellationToken)
            ?? throw new NotFoundException(request.Entity.Type.ToString(), request.Entity.Id);

        var parentId = await ResolveThreadRootAsync(request, cancellationToken);
        var body = request.Body?.Trim() ?? string.Empty;
        var mentioned = await identity.FindByUserNamesAsync(ChatMessage.ExtractMentions(body), cancellationToken);

        var message = new ChatMessage
        {
            EntityType = request.Entity.Type,
            EntityId = request.Entity.Id,
            AuthorId = authorId,
            AuthorName = currentUser.DisplayName ?? currentUser.UserName ?? "?",
            Body = body,
            ParentMessageId = parentId,
            MentionedUserIds = mentioned.Select(u => u.Id).ToList(),
            Attachments = request.Attachments
                .Select(a => new ChatAttachment { FileName = a.FileName, StoredName = a.StoredName, ContentType = a.ContentType, Size = a.Size })
                .ToList(),
        };

        db.ChatMessages.Add(message);
        db.ActivityLogs.Add(ActivityLog.For(request.Entity, entity.DisplayName, ActivityAction.Commented, Excerpt(body)));
        await db.SaveChangesAsync(cancellationToken);

        await realtime.ChatMessagePostedAsync(request.Entity, message.Id, parentId, cancellationToken);
        await notifications.NotifyAsync(
            message.MentionedUserIds.Where(id => id != authorId),
            NotificationType.Mention,
            $"{message.AuthorName} · {entity.DisplayName}: {Excerpt(body)}",
            request.Entity,
            cancellationToken);

        return message.Id;
    }

    /// <summary>Replies always attach to the top-level message so threads stay one level deep.</summary>
    private async Task<Guid?> ResolveThreadRootAsync(PostChatMessageCommand request, CancellationToken cancellationToken)
    {
        if (request.ParentMessageId is not { } parentId)
        {
            return null;
        }

        var parent = await db.ChatMessages.AsNoTracking()
            .Where(m => m.Id == parentId && m.EntityType == request.Entity.Type && m.EntityId == request.Entity.Id)
            .Select(m => new { m.Id, m.ParentMessageId })
            .FirstOrDefaultAsync(cancellationToken)
            ?? throw new NotFoundException(nameof(ChatMessage), parentId);

        return parent.ParentMessageId ?? parent.Id;
    }

    private static string Excerpt(string body)
    {
        var plain = ChatMessage.LinkPattern().Replace(body, m => "#" + m.Groups[3].Value);
        return plain.Length <= ExcerptLength ? plain : plain[..ExcerptLength] + "…";
    }
}

/// <summary>Users and objects offered by the chat composer's @ and # auto-complete.</summary>
public sealed record SearchMentionablesQuery(string? Term) : IRequest<IReadOnlyList<OptionDto>>;

internal sealed class SearchMentionablesQueryHandler(IIdentityService identity)
    : IRequestHandler<SearchMentionablesQuery, IReadOnlyList<OptionDto>>
{
    public async Task<IReadOnlyList<OptionDto>> Handle(SearchMentionablesQuery request, CancellationToken cancellationToken)
    {
        var users = await identity.GetUsersAsync(request.Term, take: 8, cancellationToken);
        return users.Where(u => u.IsActive).Select(u => new OptionDto(u.UserName, u.FullName)).ToList();
    }
}

public static class ChatPermissions
{
    public static readonly string View = Permissions.For(Permissions.Modules.Chat, Permissions.Actions.View);
    public static readonly string Create = Permissions.For(Permissions.Modules.Chat, Permissions.Actions.Create);
}
