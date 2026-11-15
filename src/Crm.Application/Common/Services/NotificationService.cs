using Crm.Domain.Collaboration;

namespace Crm.Application.Common.Services;

public sealed class NotificationService(IApplicationDbContext db, IRealtimeNotifier realtime, TimeProvider clock)
    : INotificationService
{
    private const int MaxMessageLength = 500;

    public async Task NotifyAsync(
        IEnumerable<Guid> userIds,
        NotificationType type,
        string message,
        EntityRef? entity = null,
        CancellationToken cancellationToken = default)
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var notifications = userIds.Distinct()
            .Select(userId => new Notification
            {
                UserId = userId,
                Type = type,
                Message = message.Length > MaxMessageLength ? message[..MaxMessageLength] : message,
                EntityType = entity?.Type,
                EntityId = entity?.Id,
                CreatedAt = now,
            })
            .ToList();

        if (notifications.Count == 0)
        {
            return;
        }

        db.Notifications.AddRange(notifications);
        await db.SaveChangesAsync(cancellationToken);

        foreach (var notification in notifications)
        {
            await realtime.NotificationCreatedAsync(notification, cancellationToken);
        }
    }
}
