using Crm.Application.Common.Specifications;
using Crm.Domain.Collaboration;

namespace Crm.Application.Features.Collaboration;

public sealed record ReminderDto(Guid Id, string Message, DateTime RemindAt, bool IsSent, Guid? TaskItemId);

/// <summary>Reminders of the current user that are attached to an entity.</summary>
public sealed record GetRemindersQuery(EntityRef Entity) : IRequest<IReadOnlyList<ReminderDto>>;

internal sealed class GetRemindersQueryHandler(IApplicationDbContext db, ICurrentUser currentUser)
    : IRequestHandler<GetRemindersQuery, IReadOnlyList<ReminderDto>>
{
    public async Task<IReadOnlyList<ReminderDto>> Handle(GetRemindersQuery request, CancellationToken cancellationToken) =>
        await db.Reminders.AsNoTracking()
            .Where(r => r.UserId == currentUser.UserId
                        && r.EntityType == request.Entity.Type
                        && r.EntityId == request.Entity.Id)
            .OrderBy(r => r.SentAt != null)
            .ThenBy(r => r.RemindAt)
            .Select(r => new ReminderDto(r.Id, r.Message, r.RemindAt, r.SentAt != null, r.TaskItemId))
            .ToListAsync(cancellationToken);
}

public sealed class CreateReminderCommand : IRequest<Guid>
{
    public EntityRef? Entity { get; set; }
    public string Message { get; set; } = string.Empty;
    public DateTime RemindAt { get; set; }
}

internal sealed class CreateReminderCommandValidator : AbstractValidator<CreateReminderCommand>
{
    public CreateReminderCommandValidator()
    {
        RuleFor(x => x.Message).NotEmpty().MaximumLength(500);
        RuleFor(x => x.RemindAt).NotEmpty();
    }
}

internal sealed class CreateReminderCommandHandler(
    IApplicationDbContext db,
    ICurrentUser currentUser,
    ITrackableEntityResolver resolver)
    : IRequestHandler<CreateReminderCommand, Guid>
{
    public async Task<Guid> Handle(CreateReminderCommand request, CancellationToken cancellationToken)
    {
        var userId = currentUser.UserId ?? throw new ForbiddenAccessException();
        var reminder = new Reminder
        {
            UserId = userId,
            Message = request.Message.Trim(),
            RemindAt = request.RemindAt,
        };

        if (request.Entity is { } entityRef)
        {
            var entity = await resolver.ResolveAsync(entityRef, cancellationToken)
                ?? throw new NotFoundException(entityRef.Type.ToString(), entityRef.Id);
            reminder.EntityType = entityRef.Type;
            reminder.EntityId = entityRef.Id;
            db.ActivityLogs.Add(ActivityLog.For(entityRef, entity.DisplayName, ActivityAction.ReminderSet, reminder.Message));
        }

        db.Reminders.Add(reminder);
        await db.SaveChangesAsync(cancellationToken);
        return reminder.Id;
    }
}

public sealed record DeleteReminderCommand(Guid Id) : IRequest;

internal sealed class DeleteReminderCommandHandler(IApplicationDbContext db, ICurrentUser currentUser)
    : IRequestHandler<DeleteReminderCommand>
{
    public async Task Handle(DeleteReminderCommand request, CancellationToken cancellationToken)
    {
        var reminder = await db.Reminders
            .FirstOrDefaultAsync(r => r.Id == request.Id && r.UserId == currentUser.UserId, cancellationToken)
            ?? throw new NotFoundException(nameof(Reminder), request.Id);
        db.Reminders.Remove(reminder);
        await db.SaveChangesAsync(cancellationToken);
    }
}

/// <summary>Sent by the background worker: delivers every due reminder. Returns the number processed.</summary>
public sealed record ProcessDueRemindersCommand(int BatchSize = 100) : IRequest<int>;

internal sealed class ProcessDueRemindersCommandHandler(
    IReadRepository<Reminder> reminders,
    IApplicationDbContext db,
    INotificationService notifications,
    TimeProvider clock)
    : IRequestHandler<ProcessDueRemindersCommand, int>
{
    public async Task<int> Handle(ProcessDueRemindersCommand request, CancellationToken cancellationToken)
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var due = await reminders.ListAsync(new DueRemindersSpecification(now, request.BatchSize), cancellationToken);
        if (due.Count == 0)
        {
            return 0;
        }

        // Mark first, so a crash can never deliver the same reminder twice.
        due.ForEach(r => r.MarkSent(now));
        await db.SaveChangesAsync(cancellationToken);

        foreach (var reminder in due)
        {
            EntityRef? entity = reminder is { EntityType: { } type, EntityId: { } id } ? new EntityRef(type, id) : null;
            await notifications.NotifyAsync([reminder.UserId], NotificationType.Reminder, reminder.Message, entity, cancellationToken);
        }

        return due.Count;
    }
}
