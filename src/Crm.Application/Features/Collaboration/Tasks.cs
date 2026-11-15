using Crm.Application.Common.Specifications;
using Crm.Domain.Collaboration;

namespace Crm.Application.Features.Collaboration;

public sealed record TaskDto(
    Guid Id,
    string Title,
    string? Description,
    TaskItemStatus Status,
    TaskPriority Priority,
    DateTime? DueAt,
    DateTime? CompletedAt,
    Guid? AssignedToUserId,
    string? AssignedToUserName,
    string? AssignedToRole,
    TrackableEntityType? EntityType,
    Guid? EntityId,
    string? EntityDisplayName,
    DateTime CreatedAt)
{
    public bool IsOpen => Status is TaskItemStatus.Open or TaskItemStatus.InProgress;

    public bool IsOverdue(DateTime utcNow) => IsOpen && DueAt < utcNow;
}

public enum TaskScope
{
    Mine,
    All,
}

public sealed record GetTasksQuery : PagedQuery, IRequest<PagedList<TaskDto>>
{
    public EntityRef? Entity { get; init; }
    public TaskScope Scope { get; init; } = TaskScope.Mine;
    public bool OpenOnly { get; init; }
}

internal sealed class GetTasksQueryHandler(IApplicationDbContext db, ICurrentUser currentUser)
    : IRequestHandler<GetTasksQuery, PagedList<TaskDto>>
{
    public Task<PagedList<TaskDto>> Handle(GetTasksQuery request, CancellationToken cancellationToken)
    {
        var query = db.Tasks.AsNoTracking();

        if (request.Entity is { } entity)
        {
            query = query.Where(t => t.EntityType == entity.Type && t.EntityId == entity.Id);
        }
        else if (request.Scope == TaskScope.Mine)
        {
            var userId = currentUser.UserId;
            var roles = currentUser.Roles;
            query = query.Where(t => t.AssignedToUserId == userId
                                     || t.CreatedBy == userId
                                     || (t.AssignedToRole != null && roles.Contains(t.AssignedToRole)));
        }

        if (request.OpenOnly)
        {
            query = query.Where(t => t.Status == TaskItemStatus.Open || t.Status == TaskItemStatus.InProgress);
        }

        if (!string.IsNullOrWhiteSpace(request.Search))
        {
            var term = request.Search.Trim();
            query = query.Where(t => t.Title.Contains(term) || t.EntityDisplayName!.Contains(term));
        }

        return query
            .OrderBy(t => t.Status == TaskItemStatus.Done || t.Status == TaskItemStatus.Cancelled)
            .ThenBy(t => t.DueAt ?? DateTime.MaxValue)
            .ThenByDescending(t => t.CreatedAt)
            .Select(TaskMapping.ToDto)
            .ToPagedListAsync(request, cancellationToken);
    }
}

/// <summary>Open tasks of the current user for the dashboard (uses the specification pattern).</summary>
public sealed record GetMyPendingTasksQuery(int Take = 6) : IRequest<IReadOnlyList<TaskDto>>;

internal sealed class GetMyPendingTasksQueryHandler(IReadRepository<TaskItem> tasks, ICurrentUser currentUser)
    : IRequestHandler<GetMyPendingTasksQuery, IReadOnlyList<TaskDto>>
{
    private static readonly Func<TaskItem, TaskDto> Map = TaskMapping.ToDto.Compile();

    public async Task<IReadOnlyList<TaskDto>> Handle(GetMyPendingTasksQuery request, CancellationToken cancellationToken)
    {
        if (currentUser.UserId is not { } userId)
        {
            return [];
        }

        var items = await tasks.ListAsync(
            new OpenTasksForUserSpecification(userId, currentUser.Roles, request.Take), cancellationToken);
        return items.Select(Map).ToList();
    }
}

internal static class TaskMapping
{
    public static readonly System.Linq.Expressions.Expression<Func<TaskItem, TaskDto>> ToDto = t => new TaskDto(
        t.Id, t.Title, t.Description, t.Status, t.Priority, t.DueAt, t.CompletedAt,
        t.AssignedToUserId, t.AssignedToUserName, t.AssignedToRole,
        t.EntityType, t.EntityId, t.EntityDisplayName, t.CreatedAt);
}

/// <summary>Creates a task, optionally bound to an entity, assigned to a user and/or a role.</summary>
public sealed class CreateTaskCommand : IRequest<Guid>
{
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
    public TaskPriority Priority { get; set; } = TaskPriority.Normal;
    public DateTime? DueAt { get; set; }
    public Guid? AssignedToUserId { get; set; }
    public string? AssignedToRole { get; set; }
    public EntityRef? Entity { get; set; }

    /// <summary>When set, a reminder is scheduled for the assignee (or the creator).</summary>
    public DateTime? RemindAt { get; set; }
}

internal sealed class CreateTaskCommandValidator : AbstractValidator<CreateTaskCommand>
{
    public CreateTaskCommandValidator()
    {
        RuleFor(x => x.Title).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Description).MaximumLength(4000);
        RuleFor(x => x.Priority).IsInEnum();
        RuleFor(x => x.AssignedToRole).MaximumLength(256);
    }
}

internal sealed class CreateTaskCommandHandler(
    IApplicationDbContext db,
    ICurrentUser currentUser,
    ITrackableEntityResolver resolver,
    IIdentityService identity,
    INotificationService notifications)
    : IRequestHandler<CreateTaskCommand, Guid>
{
    public async Task<Guid> Handle(CreateTaskCommand request, CancellationToken cancellationToken)
    {
        var task = new TaskItem
        {
            Title = request.Title.Trim(),
            Description = request.Description,
            Priority = request.Priority,
            DueAt = request.DueAt,
            AssignedToRole = string.IsNullOrWhiteSpace(request.AssignedToRole) ? null : request.AssignedToRole,
        };

        if (request.AssignedToUserId is { } assigneeId)
        {
            var assignee = await identity.GetUserAsync(assigneeId, cancellationToken)
                ?? throw new NotFoundException("User", assigneeId);
            task.AssignedToUserId = assignee.Id;
            task.AssignedToUserName = assignee.FullName;
        }

        if (request.Entity is { } entityRef)
        {
            var entity = await resolver.ResolveAsync(entityRef, cancellationToken)
                ?? throw new NotFoundException(entityRef.Type.ToString(), entityRef.Id);
            task.BindTo(entityRef, entity.DisplayName);
            db.ActivityLogs.Add(ActivityLog.For(entityRef, entity.DisplayName, ActivityAction.TaskCreated, task.Title));
        }

        if (request.RemindAt is { } remindAt && (task.AssignedToUserId ?? currentUser.UserId) is { } reminderUserId)
        {
            task.Reminders.Add(new Reminder
            {
                UserId = reminderUserId,
                Message = task.Title,
                RemindAt = remindAt,
                EntityType = task.EntityType,
                EntityId = task.EntityId,
            });
        }

        db.Tasks.Add(task);
        await db.SaveChangesAsync(cancellationToken);

        await notifications.NotifyAsync(
            await GetRecipientsAsync(task, cancellationToken),
            NotificationType.TaskAssigned,
            task.EntityDisplayName is null ? task.Title : $"{task.Title} · {task.EntityDisplayName}",
            request.Entity,
            cancellationToken);

        return task.Id;
    }

    private async Task<IEnumerable<Guid>> GetRecipientsAsync(TaskItem task, CancellationToken cancellationToken)
    {
        var recipients = new HashSet<Guid>();
        if (task.AssignedToUserId is { } userId)
        {
            recipients.Add(userId);
        }

        if (task.AssignedToRole is not null)
        {
            recipients.UnionWith(await identity.GetUserIdsInRoleAsync(task.AssignedToRole, cancellationToken));
        }

        if (currentUser.UserId is { } creatorId)
        {
            recipients.Remove(creatorId);
        }

        return recipients;
    }
}

public sealed record ChangeTaskStatusCommand(Guid Id, TaskItemStatus Status) : IRequest;

internal sealed class ChangeTaskStatusCommandHandler(IApplicationDbContext db, TimeProvider clock)
    : IRequestHandler<ChangeTaskStatusCommand>
{
    public async Task Handle(ChangeTaskStatusCommand request, CancellationToken cancellationToken)
    {
        var task = await db.Tasks.FirstOrDefaultAsync(t => t.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(TaskItem), request.Id);

        task.ChangeStatus(request.Status, clock.GetUtcNow().UtcDateTime);

        if (request.Status == TaskItemStatus.Done && task is { EntityType: { } type, EntityId: { } entityId })
        {
            db.ActivityLogs.Add(ActivityLog.For(
                new EntityRef(type, entityId), task.EntityDisplayName ?? string.Empty, ActivityAction.TaskCompleted, task.Title));
        }

        await db.SaveChangesAsync(cancellationToken);
    }
}

public sealed record DeleteTaskCommand(Guid Id) : IRequest;

internal sealed class DeleteTaskCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteTaskCommand>
{
    public async Task Handle(DeleteTaskCommand request, CancellationToken cancellationToken)
    {
        var task = await db.Tasks.Include(t => t.Reminders).FirstOrDefaultAsync(t => t.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(TaskItem), request.Id);
        db.Reminders.RemoveRange(task.Reminders.Where(r => !r.IsSent));
        db.Tasks.Remove(task);
        await db.SaveChangesAsync(cancellationToken);
    }
}
