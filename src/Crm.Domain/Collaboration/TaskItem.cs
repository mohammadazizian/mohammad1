using Crm.Domain.Common;

namespace Crm.Domain.Collaboration;

public enum TaskItemStatus
{
    Open = 1,
    InProgress = 2,
    Done = 3,
    Cancelled = 4,
}

public enum TaskPriority
{
    Low = 1,
    Normal = 2,
    High = 3,
    Urgent = 4,
}

/// <summary>A task assignable to a user and/or a role, optionally bound to any trackable entity.</summary>
public class TaskItem : AuditableEntity
{
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
    public TaskItemStatus Status { get; private set; } = TaskItemStatus.Open;
    public TaskPriority Priority { get; set; } = TaskPriority.Normal;
    public DateTime? DueAt { get; set; }
    public DateTime? CompletedAt { get; private set; }

    public Guid? AssignedToUserId { get; set; }
    public string? AssignedToUserName { get; set; }
    public string? AssignedToRole { get; set; }

    // Polymorphic binding (optional: a task may be standalone).
    public TrackableEntityType? EntityType { get; set; }
    public Guid? EntityId { get; set; }
    public string? EntityDisplayName { get; set; }

    public ICollection<Reminder> Reminders { get; } = [];

    public bool IsOpen => Status is TaskItemStatus.Open or TaskItemStatus.InProgress;

    public bool IsOverdue(DateTime utcNow) => IsOpen && DueAt < utcNow;

    public void BindTo(EntityRef entity, string displayName)
    {
        EntityType = entity.Type;
        EntityId = entity.Id;
        EntityDisplayName = displayName;
    }

    public void ChangeStatus(TaskItemStatus status, DateTime utcNow)
    {
        if (Status == status)
        {
            return;
        }

        Status = status;
        CompletedAt = status == TaskItemStatus.Done ? utcNow : null;
        if (status == TaskItemStatus.Done)
        {
            AddDomainEvent(new TaskCompletedEvent(Id));
        }
    }
}

public sealed record TaskCompletedEvent(Guid TaskId) : IDomainEvent;

/// <summary>A scheduled alert for one user, optionally tied to a task and/or a trackable entity.</summary>
public class Reminder : AuditableEntity
{
    public Guid UserId { get; set; }
    public string Message { get; set; } = string.Empty;
    public DateTime RemindAt { get; set; }
    public DateTime? SentAt { get; private set; }

    public Guid? TaskItemId { get; set; }
    public TaskItem? TaskItem { get; set; }
    public TrackableEntityType? EntityType { get; set; }
    public Guid? EntityId { get; set; }

    public bool IsSent => SentAt is not null;

    public bool IsDue(DateTime utcNow) => !IsSent && RemindAt <= utcNow;

    public void MarkSent(DateTime utcNow) => SentAt = utcNow;
}
