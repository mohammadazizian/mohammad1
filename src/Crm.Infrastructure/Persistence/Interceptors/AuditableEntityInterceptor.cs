using Crm.Domain.Collaboration;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace Crm.Infrastructure.Persistence.Interceptors;

/// <summary>
/// Cross-cutting persistence rules, applied on every save:
/// audit stamps, soft-delete, and automatic activity logging of trackable entities.
/// </summary>
public sealed class AuditableEntityInterceptor(ICurrentUser currentUser, TimeProvider clock) : SaveChangesInterceptor
{
    private static readonly HashSet<string> AuditProperties =
    [
        nameof(IAuditable.CreatedAt), nameof(IAuditable.CreatedBy), nameof(IAuditable.ModifiedAt), nameof(IAuditable.ModifiedBy),
        nameof(ISoftDelete.IsDeleted), nameof(ISoftDelete.DeletedAt), nameof(ISoftDelete.DeletedBy),
    ];

    public override InterceptionResult<int> SavingChanges(DbContextEventData eventData, InterceptionResult<int> result)
    {
        Apply(eventData.Context);
        return base.SavingChanges(eventData, result);
    }

    public override ValueTask<InterceptionResult<int>> SavingChangesAsync(
        DbContextEventData eventData,
        InterceptionResult<int> result,
        CancellationToken cancellationToken = default)
    {
        Apply(eventData.Context);
        return base.SavingChangesAsync(eventData, result, cancellationToken);
    }

    private void Apply(DbContext? context)
    {
        if (context is null)
        {
            return;
        }

        var now = clock.GetUtcNow().UtcDateTime;
        var userId = currentUser.UserId;
        var activities = new List<ActivityLog>();

        foreach (var entry in context.ChangeTracker.Entries().ToList())
        {
            switch (entry.State)
            {
                case EntityState.Added:
                    if (entry.Entity is IAuditable added)
                    {
                        added.CreatedAt = now;
                        added.CreatedBy ??= userId;
                    }

                    Track(entry, ActivityAction.Created, activities);
                    break;

                case EntityState.Modified:
                    if (entry.Entity is IAuditable modified)
                    {
                        modified.ModifiedAt = now;
                        modified.ModifiedBy = userId;
                    }

                    Track(entry, ActivityAction.Updated, activities, DescribeChanges(entry));
                    break;

                case EntityState.Deleted when entry.Entity is ISoftDelete deleted:
                    // Turn the physical delete into a flag update.
                    entry.State = EntityState.Unchanged;
                    deleted.IsDeleted = true;
                    deleted.DeletedAt = now;
                    deleted.DeletedBy = userId;
                    Track(entry, ActivityAction.Deleted, activities);
                    break;
            }
        }

        context.AddRange(activities);

        foreach (var log in context.ChangeTracker.Entries<ActivityLog>().Where(e => e.State == EntityState.Added))
        {
            log.Entity.OccurredAt = now;
            log.Entity.UserId ??= userId;
            log.Entity.UserName ??= currentUser.DisplayName ?? currentUser.UserName;
        }
    }

    private static void Track(EntityEntry entry, ActivityAction action, List<ActivityLog> activities, string? details = null)
    {
        if (entry.Entity is ITrackableEntity trackable && (action != ActivityAction.Updated || details is not null))
        {
            activities.Add(ActivityLog.For(trackable, action, details));
        }
    }

    /// <summary>Lists the changed business fields, or null when only bookkeeping fields changed.</summary>
    private static string? DescribeChanges(EntityEntry entry)
    {
        var changed = entry.Properties
            .Where(p => p.IsModified && !p.Metadata.IsShadowProperty() && !AuditProperties.Contains(p.Metadata.Name))
            .Select(p => p.Metadata.Name)
            .Concat(entry.ComplexProperties.Where(c => c.IsModified).Select(c => c.Metadata.Name))
            .Distinct()
            .ToList();

        return changed.Count == 0 ? null : string.Join(", ", changed);
    }
}
