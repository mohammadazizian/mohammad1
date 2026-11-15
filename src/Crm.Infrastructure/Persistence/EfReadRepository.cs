using Crm.Application.Common.Specifications;

namespace Crm.Infrastructure.Persistence;

/// <summary>Evaluates specifications against EF Core.</summary>
public sealed class EfReadRepository<T>(ApplicationDbContext db) : IReadRepository<T>
    where T : class
{
    public Task<List<T>> ListAsync(Specification<T> specification, CancellationToken cancellationToken = default) =>
        Apply(specification).ToListAsync(cancellationToken);

    public Task<int> CountAsync(Specification<T> specification, CancellationToken cancellationToken = default) =>
        Apply(specification, forCount: true).CountAsync(cancellationToken);

    public Task<T?> FirstOrDefaultAsync(Specification<T> specification, CancellationToken cancellationToken = default) =>
        Apply(specification).FirstOrDefaultAsync(cancellationToken);

    private IQueryable<T> Apply(Specification<T> specification, bool forCount = false)
    {
        IQueryable<T> query = db.Set<T>();
        if (!specification.AsTracking)
        {
            query = query.AsNoTracking();
        }

        if (specification.Criteria is not null)
        {
            query = query.Where(specification.Criteria);
        }

        if (forCount)
        {
            return query;
        }

        query = specification.Includes.Aggregate(query, (current, include) => current.Include(include));

        if (specification.OrderBy is not null)
        {
            query = query.OrderBy(specification.OrderBy);
        }
        else if (specification.OrderByDescending is not null)
        {
            query = query.OrderByDescending(specification.OrderByDescending);
        }

        return specification.Take is { } take ? query.Take(take) : query;
    }
}
