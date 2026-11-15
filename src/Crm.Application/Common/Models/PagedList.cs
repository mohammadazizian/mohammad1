namespace Crm.Application.Common.Models;

public sealed class PagedList<T>(IReadOnlyList<T> items, int totalCount, int page, int pageSize)
{
    public IReadOnlyList<T> Items { get; } = items;
    public int TotalCount { get; } = totalCount;
    public int Page { get; } = page;
    public int PageSize { get; } = pageSize;
    public int TotalPages => (int)Math.Ceiling(TotalCount / (double)PageSize);
    public bool HasPrevious => Page > 1;
    public bool HasNext => Page < TotalPages;
}

/// <summary>Common paging parameters of list queries.</summary>
public abstract record PagedQuery
{
    private const int MaxPageSize = 100;

    public int Page { get; init; } = 1;
    public int PageSize { get; init; } = 15;
    public string? Search { get; init; }

    internal int SafePage => Math.Max(1, Page);
    internal int SafePageSize => Math.Clamp(PageSize, 1, MaxPageSize);
}

public static class PagingExtensions
{
    public static async Task<PagedList<T>> ToPagedListAsync<T>(
        this IQueryable<T> query,
        PagedQuery paging,
        CancellationToken cancellationToken)
    {
        var total = await query.CountAsync(cancellationToken);
        var items = await query
            .Skip((paging.SafePage - 1) * paging.SafePageSize)
            .Take(paging.SafePageSize)
            .ToListAsync(cancellationToken);
        return new PagedList<T>(items, total, paging.SafePage, paging.SafePageSize);
    }
}

/// <summary>Generic value/label pair for dropdowns.</summary>
public sealed record OptionDto(string Value, string Label);
