using System.Linq.Expressions;
using Crm.Domain.Collaboration;
using Crm.Domain.Inventory;

namespace Crm.Application.Common.Specifications;

/// <summary>Encapsulates a reusable, named query rule (Specification pattern).</summary>
public abstract class Specification<T>
    where T : class
{
    public Expression<Func<T, bool>>? Criteria { get; private set; }
    public List<Expression<Func<T, object?>>> Includes { get; } = [];
    public Expression<Func<T, object?>>? OrderBy { get; private set; }
    public Expression<Func<T, object?>>? OrderByDescending { get; private set; }
    public int? Take { get; private set; }
    public bool AsTracking { get; private set; }

    protected void Where(Expression<Func<T, bool>> criteria) => Criteria = criteria;

    protected void Include(Expression<Func<T, object?>> include) => Includes.Add(include);

    protected void ApplyOrderBy(Expression<Func<T, object?>> orderBy) => OrderBy = orderBy;

    protected void ApplyOrderByDescending(Expression<Func<T, object?>> orderBy) => OrderByDescending = orderBy;

    protected void Limit(int take) => Take = take;

    protected void Tracked() => AsTracking = true;
}

/// <summary>Read-side repository evaluating specifications.</summary>
public interface IReadRepository<T>
    where T : class
{
    Task<List<T>> ListAsync(Specification<T> specification, CancellationToken cancellationToken = default);
    Task<int> CountAsync(Specification<T> specification, CancellationToken cancellationToken = default);
    Task<T?> FirstOrDefaultAsync(Specification<T> specification, CancellationToken cancellationToken = default);
}

/// <summary>Active products whose total stock is at or below their low-stock threshold.</summary>
public sealed class LowStockProductsSpecification : Specification<Product>
{
    public LowStockProductsSpecification(int? take = null)
    {
        Where(p => p.IsActive && p.StockLevels.Sum(s => s.Quantity) <= p.LowStockThreshold);
        Include(p => p.StockLevels);
        ApplyOrderBy(p => p.Name);
        if (take is not null)
        {
            Limit(take.Value);
        }
    }
}

/// <summary>Unsent reminders whose time has come (tracked, so they can be marked as sent).</summary>
public sealed class DueRemindersSpecification : Specification<Reminder>
{
    public DueRemindersSpecification(DateTime utcNow, int batchSize)
    {
        Where(r => r.SentAt == null && r.RemindAt <= utcNow);
        ApplyOrderBy(r => r.RemindAt);
        Limit(batchSize);
        Tracked();
    }
}

/// <summary>Open tasks assigned to a user directly or through one of their roles.</summary>
public sealed class OpenTasksForUserSpecification : Specification<TaskItem>
{
    public OpenTasksForUserSpecification(Guid userId, IReadOnlyCollection<string> roles, int take)
    {
        Where(t => (t.Status == TaskItemStatus.Open || t.Status == TaskItemStatus.InProgress)
                   && (t.AssignedToUserId == userId || (t.AssignedToRole != null && roles.Contains(t.AssignedToRole))));
        ApplyOrderBy(t => t.DueAt ?? DateTime.MaxValue);
        Limit(take);
    }
}
