namespace Crm.Application.Common.Services;

/// <summary>
/// The single place that knows which table backs each <see cref="TrackableEntityType"/>.
/// Supporting a new trackable entity means adding one case to <see cref="Query"/>.
/// </summary>
public sealed class TrackableEntityResolver(IApplicationDbContext db) : ITrackableEntityResolver
{
    public async Task<TrackableInfo?> ResolveAsync(EntityRef reference, CancellationToken cancellationToken = default) =>
        await Query(reference.Type, null, reference.Id).FirstOrDefaultAsync(cancellationToken);

    public async Task<IReadOnlyList<TrackableInfo>> SearchAsync(
        string? term,
        TrackableEntityType? type = null,
        int take = 10,
        CancellationToken cancellationToken = default)
    {
        term = string.IsNullOrWhiteSpace(term) ? null : term.Trim();
        var types = type is not null ? [type.Value] : Enum.GetValues<TrackableEntityType>();
        var perType = type is not null ? take : Math.Max(3, take / 2);

        var results = new List<TrackableInfo>();
        foreach (var entityType in types)
        {
            results.AddRange(await Query(entityType, term).Take(perType).ToListAsync(cancellationToken));
        }

        return results.Take(type is not null ? take : take * 2).ToList();
    }

    private IQueryable<TrackableInfo> Query(TrackableEntityType type, string? term, Guid? id = null) => type switch
    {
        TrackableEntityType.Customer => db.Customers.AsNoTracking()
            .Where(e => (id == null || e.Id == id) && (term == null || e.Name.Contains(term)))
            .OrderBy(e => e.Name)
            .Select(e => new TrackableInfo(type, e.Id, e.Name)),
        TrackableEntityType.Product => db.Products.AsNoTracking()
            .Where(e => (id == null || e.Id == id) && (term == null || e.Name.Contains(term) || e.Sku.Contains(term)))
            .OrderBy(e => e.Name)
            .Select(e => new TrackableInfo(type, e.Id, e.Name + " (" + e.Sku + ")")),
        TrackableEntityType.InventoryTransaction => db.InventoryTransactions.AsNoTracking()
            .Where(e => (id == null || e.Id == id) && (term == null || e.Number.Contains(term)))
            .OrderByDescending(e => e.OccurredAt)
            .Select(e => new TrackableInfo(type, e.Id, e.Number)),
        TrackableEntityType.FormSubmission => db.FormSubmissions.AsNoTracking()
            .Where(e => (id == null || e.Id == id) && (term == null || e.Title.Contains(term)))
            .OrderByDescending(e => e.CreatedAt)
            .Select(e => new TrackableInfo(type, e.Id, e.Title)),
        TrackableEntityType.Lead => db.Leads.AsNoTracking()
            .Where(e => (id == null || e.Id == id) && (term == null || e.Name.Contains(term) || e.Company!.Contains(term)))
            .OrderBy(e => e.Name)
            .Select(e => new TrackableInfo(type, e.Id, e.Company == null || e.Company == "" ? e.Name : e.Name + " (" + e.Company + ")")),
        TrackableEntityType.Deal => db.Deals.AsNoTracking()
            .Where(e => (id == null || e.Id == id) && (term == null || e.Title.Contains(term)))
            .OrderByDescending(e => e.CreatedAt)
            .Select(e => new TrackableInfo(type, e.Id, e.Title)),
        _ => throw new ArgumentOutOfRangeException(nameof(type), type, "Unsupported trackable entity type."),
    };
}
