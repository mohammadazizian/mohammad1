using Crm.Domain.Common;

namespace Crm.Domain.Collaboration;

public enum ActivityAction
{
    Created = 1,
    Updated = 2,
    Deleted = 3,
    Commented = 4,
    TaskCreated = 5,
    TaskCompleted = 6,
    ReminderSet = 7,
    StageChanged = 8,
    Converted = 9,
}

/// <summary>Append-only timeline entry of a trackable entity.</summary>
public class ActivityLog : BaseEntity
{
    public TrackableEntityType EntityType { get; set; }
    public Guid EntityId { get; set; }
    public string EntityDisplayName { get; set; } = string.Empty;
    public ActivityAction Action { get; set; }
    public string? Details { get; set; }
    public Guid? UserId { get; set; }
    public string? UserName { get; set; }
    public DateTime OccurredAt { get; set; }

    public static ActivityLog For(ITrackableEntity entity, ActivityAction action, string? details = null) =>
        For(EntityRef.Of(entity), entity.DisplayName, action, details);

    public static ActivityLog For(EntityRef entity, string displayName, ActivityAction action, string? details = null) => new()
    {
        EntityType = entity.Type,
        EntityId = entity.Id,
        EntityDisplayName = displayName,
        Action = action,
        Details = details,
    };
}

public enum NotificationType
{
    Mention = 1,
    TaskAssigned = 2,
    Reminder = 3,
    LowStock = 4,
}

/// <summary>In-app notification of a single user (also pushed in real time).</summary>
public class Notification : BaseEntity
{
    public Guid UserId { get; set; }
    public NotificationType Type { get; set; }
    public string Message { get; set; } = string.Empty;
    public TrackableEntityType? EntityType { get; set; }
    public Guid? EntityId { get; set; }
    public bool IsRead { get; set; }
    public DateTime CreatedAt { get; set; }
}
