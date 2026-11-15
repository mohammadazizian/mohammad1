using Crm.Application.Common.Behaviors;
using MediatR;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Logging;

namespace Crm.Infrastructure.Persistence.Interceptors;

/// <summary>
/// Publishes the domain events of saved entities through MediatR once the data is committed.
/// A failing side effect is logged; it never fails the business operation that raised it.
/// </summary>
public sealed class DispatchDomainEventsInterceptor(IPublisher publisher, ILogger<DispatchDomainEventsInterceptor> logger)
    : SaveChangesInterceptor
{
    public override async ValueTask<int> SavedChangesAsync(
        SaveChangesCompletedEventData eventData,
        int result,
        CancellationToken cancellationToken = default)
    {
        if (eventData.Context is { } context)
        {
            var entities = context.ChangeTracker.Entries<BaseEntity>()
                .Select(e => e.Entity)
                .Where(e => e.DomainEvents.Count != 0)
                .ToList();
            var events = entities.SelectMany(e => e.DomainEvents).ToList();
            entities.ForEach(e => e.ClearDomainEvents());

            foreach (var domainEvent in events)
            {
                try
                {
                    var notificationType = typeof(DomainEventNotification<>).MakeGenericType(domainEvent.GetType());
                    await publisher.Publish(Activator.CreateInstance(notificationType, domainEvent)!, cancellationToken);
                }
                catch (Exception ex)
                {
                    logger.LogError(ex, "Handling domain event {DomainEvent} failed", domainEvent.GetType().Name);
                }
            }
        }

        return await base.SavedChangesAsync(eventData, result, cancellationToken);
    }
}
