using Crm.Domain.Collaboration;

namespace Crm.Application.Features.Collaboration;

public sealed record ActivityDto(
    Guid Id,
    TrackableEntityType EntityType,
    Guid EntityId,
    string EntityDisplayName,
    ActivityAction Action,
    string? Details,
    string? UserName,
    DateTime OccurredAt);

/// <summary>Activity timeline of one entity, or the latest activities system-wide when no entity is given.</summary>
public sealed record GetActivityQuery(EntityRef? Entity = null, int Take = 20) : IRequest<IReadOnlyList<ActivityDto>>;

internal sealed class GetActivityQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetActivityQuery, IReadOnlyList<ActivityDto>>
{
    public async Task<IReadOnlyList<ActivityDto>> Handle(GetActivityQuery request, CancellationToken cancellationToken)
    {
        var query = db.ActivityLogs.AsNoTracking();
        if (request.Entity is { } entity)
        {
            query = query.Where(a => a.EntityType == entity.Type && a.EntityId == entity.Id);
        }

        return await query
            .OrderByDescending(a => a.OccurredAt)
            .Take(Math.Clamp(request.Take, 1, 200))
            .Select(a => new ActivityDto(
                a.Id, a.EntityType, a.EntityId, a.EntityDisplayName, a.Action, a.Details, a.UserName, a.OccurredAt))
            .ToListAsync(cancellationToken);
    }
}

public sealed record NotificationDto(
    Guid Id,
    NotificationType Type,
    string Message,
    TrackableEntityType? EntityType,
    Guid? EntityId,
    bool IsRead,
    DateTime CreatedAt);

public sealed record NotificationListDto(IReadOnlyList<NotificationDto> Items, int UnreadCount);

public sealed record GetNotificationsQuery(int Take = 15) : IRequest<NotificationListDto>;

internal sealed class GetNotificationsQueryHandler(IApplicationDbContext db, ICurrentUser currentUser)
    : IRequestHandler<GetNotificationsQuery, NotificationListDto>
{
    public async Task<NotificationListDto> Handle(GetNotificationsQuery request, CancellationToken cancellationToken)
    {
        var mine = db.Notifications.AsNoTracking().Where(n => n.UserId == currentUser.UserId);
        var items = await mine
            .OrderByDescending(n => n.CreatedAt)
            .Take(Math.Clamp(request.Take, 1, 200))
            .Select(n => new NotificationDto(n.Id, n.Type, n.Message, n.EntityType, n.EntityId, n.IsRead, n.CreatedAt))
            .ToListAsync(cancellationToken);
        var unread = await mine.CountAsync(n => !n.IsRead, cancellationToken);
        return new NotificationListDto(items, unread);
    }
}

/// <summary>Marks one notification (or all of them when <see cref="Id"/> is null) as read.</summary>
public sealed record MarkNotificationsReadCommand(Guid? Id = null) : IRequest;

internal sealed class MarkNotificationsReadCommandHandler(IApplicationDbContext db, ICurrentUser currentUser)
    : IRequestHandler<MarkNotificationsReadCommand>
{
    public async Task Handle(MarkNotificationsReadCommand request, CancellationToken cancellationToken)
    {
        var unread = await db.Notifications
            .Where(n => n.UserId == currentUser.UserId && !n.IsRead && (request.Id == null || n.Id == request.Id))
            .ToListAsync(cancellationToken);
        unread.ForEach(n => n.IsRead = true);
        await db.SaveChangesAsync(cancellationToken);
    }
}

public sealed record CollaborationSummaryDto(int MessageCount, int OpenTaskCount);

/// <summary>Counters shown on the chat / task buttons of an entity page.</summary>
public sealed record GetCollaborationSummaryQuery(EntityRef Entity) : IRequest<CollaborationSummaryDto>;

internal sealed class GetCollaborationSummaryQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetCollaborationSummaryQuery, CollaborationSummaryDto>
{
    public async Task<CollaborationSummaryDto> Handle(GetCollaborationSummaryQuery request, CancellationToken cancellationToken)
    {
        var entity = request.Entity;
        return new CollaborationSummaryDto(
            await db.ChatMessages.CountAsync(m => m.EntityType == entity.Type && m.EntityId == entity.Id, cancellationToken),
            await db.Tasks.CountAsync(
                t => t.EntityType == entity.Type && t.EntityId == entity.Id
                     && (t.Status == TaskItemStatus.Open || t.Status == TaskItemStatus.InProgress),
                cancellationToken));
    }
}
