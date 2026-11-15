using System.Globalization;
using System.Linq.Expressions;
using System.Reflection;
using Crm.Application.Common.Security;

namespace Crm.Application.Features.Reports;

internal interface IReportSource
{
    ReportSourceInfo Info { get; }

    Task<ReportResult> RunAsync(IApplicationDbContext db, ReportDefinition definition, bool persian, CancellationToken cancellationToken);
}

/// <summary>
/// Generic report runner: translates the user's filters and sorting to an expression tree that
/// EF Core executes in SQL, then groups / aggregates the (bounded) result in memory.
/// </summary>
internal sealed class ReportSource<TRow>(
    string key,
    string module,
    Func<IApplicationDbContext, bool, IQueryable<TRow>> query) : IReportSource
    where TRow : class
{
    public const int MaxRows = 5000;

    private static readonly PropertyInfo[] Properties = typeof(TRow).GetProperties(BindingFlags.Public | BindingFlags.Instance);

    public ReportSourceInfo Info { get; } = new(
        key,
        Permissions.For(module, Permissions.Actions.View),
        Properties.Select(p => new ReportColumnInfo(p.Name, ColumnTypeOf(p.PropertyType), p.PropertyType)).ToList());

    public async Task<ReportResult> RunAsync(
        IApplicationDbContext db,
        ReportDefinition definition,
        bool persian,
        CancellationToken cancellationToken)
    {
        var rows = query(db, persian);

        foreach (var filter in definition.Filters.Where(f => !string.IsNullOrWhiteSpace(f.Value)))
        {
            rows = rows.Where(BuildPredicate(filter));
        }

        var sortProperty = FindProperty(definition.SortBy) ?? Properties[0];
        rows = ApplySort(rows, sortProperty, definition.SortDescending);

        var data = await rows.Take(MaxRows + 1).ToListAsync(cancellationToken);
        var truncated = data.Count > MaxRows;
        if (truncated)
        {
            data.RemoveAt(data.Count - 1);
        }

        var selected = definition.Columns
            .Select(FindProperty)
            .Where(p => p is not null)
            .Select(p => p!)
            .Distinct()
            .ToList();
        if (selected.Count == 0)
        {
            selected = [.. Properties];
        }

        var columns = selected.Select(p => Info.Columns.First(c => c.Key == p.Name)).ToList();
        var table = data.Select(row => selected.Select(p => p.GetValue(row)).ToArray()).ToList();

        var groupProperty = FindProperty(definition.GroupBy);
        var groups = groupProperty is null ? [] : Group(data, groupProperty, definition);
        var groupColumn = groupProperty is null ? null : Info.Columns.First(c => c.Key == groupProperty.Name);

        return new ReportResult(Info, definition, columns, table, groupColumn, groups, truncated);
    }

    private static List<ReportGroup> Group(List<TRow> data, PropertyInfo groupProperty, ReportDefinition definition)
    {
        var valueProperty = FindProperty(definition.AggregateColumn);
        var aggregate = valueProperty is null || ColumnTypeOf(valueProperty.PropertyType) != ReportColumnType.Number
            ? ReportAggregate.Count
            : definition.Aggregate;

        return data
            .GroupBy(row => GroupKey(groupProperty.GetValue(row)))
            .Select(group =>
            {
                var values = aggregate == ReportAggregate.Count
                    ? []
                    : group.Select(row => Convert.ToDecimal(valueProperty!.GetValue(row) ?? 0m, CultureInfo.InvariantCulture)).ToList();
                var value = aggregate switch
                {
                    ReportAggregate.Sum => values.Sum(),
                    ReportAggregate.Average => values.Count == 0 ? 0 : Math.Round(values.Average(), 2),
                    ReportAggregate.Min => values.Count == 0 ? 0 : values.Min(),
                    ReportAggregate.Max => values.Count == 0 ? 0 : values.Max(),
                    _ => group.Count(),
                };
                return new ReportGroup(group.Key, value, group.Count());
            })
            .OrderByDescending(g => g.Value)
            .ToList();
    }

    /// <summary>Dates are grouped per month, everything else by its exact value.</summary>
    private static object? GroupKey(object? value) => value switch
    {
        DateTime date => new DateTime(date.Year, date.Month, 1, 0, 0, 0, DateTimeKind.Utc),
        string { Length: 0 } => null,
        _ => value,
    };

    private static IQueryable<TRow> ApplySort(IQueryable<TRow> rows, PropertyInfo property, bool descending)
    {
        var parameter = Expression.Parameter(typeof(TRow), "r");
        var selector = Expression.Lambda(Expression.Property(parameter, property), parameter);
        var method = descending ? nameof(Queryable.OrderByDescending) : nameof(Queryable.OrderBy);
        var call = Expression.Call(typeof(Queryable), method, [typeof(TRow), property.PropertyType], rows.Expression, Expression.Quote(selector));
        return rows.Provider.CreateQuery<TRow>(call);
    }

    private static Expression<Func<TRow, bool>> BuildPredicate(ReportFilter filter)
    {
        var property = FindProperty(filter.Column)
            ?? throw new AppValidationException(nameof(ReportDefinition.Filters), $"Unknown column '{filter.Column}'.");
        var parameter = Expression.Parameter(typeof(TRow), "r");
        var member = Expression.Property(parameter, property);
        var raw = filter.Value!.Trim();

        Expression body;
        switch (ColumnTypeOf(property.PropertyType))
        {
            case ReportColumnType.Text:
                var text = Expression.Constant(raw, typeof(string));
                body = filter.Operator switch
                {
                    ReportOperators.Equal => Expression.Equal(member, text),
                    ReportOperators.NotEqual => Expression.NotEqual(member, text),
                    ReportOperators.StartsWith => Expression.Call(member, nameof(string.StartsWith), Type.EmptyTypes, text),
                    _ => Expression.Call(member, nameof(string.Contains), Type.EmptyTypes, text),
                };
                break;

            case ReportColumnType.Date:
                if (!DateTime.TryParseExact(raw, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var day))
                {
                    throw Invalid(filter);
                }

                var start = Expression.Constant(day, property.PropertyType);
                var end = Expression.Constant(day.AddDays(1), property.PropertyType);
                body = filter.Operator switch
                {
                    ReportOperators.GreaterThan => Expression.GreaterThanOrEqual(member, end),
                    ReportOperators.GreaterOrEqual => Expression.GreaterThanOrEqual(member, start),
                    ReportOperators.LessThan => Expression.LessThan(member, start),
                    ReportOperators.LessOrEqual => Expression.LessThan(member, end),
                    ReportOperators.NotEqual => Expression.OrElse(Expression.LessThan(member, start), Expression.GreaterThanOrEqual(member, end)),
                    _ => Expression.AndAlso(Expression.GreaterThanOrEqual(member, start), Expression.LessThan(member, end)),
                };
                break;

            default:
                var constant = Expression.Constant(ParseValue(filter, raw, property.PropertyType), property.PropertyType);
                body = filter.Operator switch
                {
                    ReportOperators.NotEqual => Expression.NotEqual(member, constant),
                    ReportOperators.GreaterThan => Expression.GreaterThan(member, constant),
                    ReportOperators.GreaterOrEqual => Expression.GreaterThanOrEqual(member, constant),
                    ReportOperators.LessThan => Expression.LessThan(member, constant),
                    ReportOperators.LessOrEqual => Expression.LessThanOrEqual(member, constant),
                    _ => Expression.Equal(member, constant),
                };
                break;
        }

        return Expression.Lambda<Func<TRow, bool>>(body, parameter);
    }

    private static object ParseValue(ReportFilter filter, string raw, Type propertyType)
    {
        var type = Nullable.GetUnderlyingType(propertyType) ?? propertyType;
        try
        {
            if (type.IsEnum)
            {
                return Enum.Parse(type, raw, ignoreCase: true);
            }

            if (type == typeof(bool))
            {
                return raw is "1" || bool.Parse(raw);
            }

            return Convert.ChangeType(decimal.Parse(raw, NumberStyles.Number, CultureInfo.InvariantCulture), type, CultureInfo.InvariantCulture);
        }
        catch (Exception ex) when (ex is FormatException or ArgumentException or OverflowException)
        {
            throw Invalid(filter);
        }
    }

    private static AppValidationException Invalid(ReportFilter filter) =>
        new(nameof(ReportDefinition.Filters), $"'{filter.Value}' is not a valid value for '{filter.Column}'.");

    private static PropertyInfo? FindProperty(string? name) =>
        string.IsNullOrWhiteSpace(name)
            ? null
            : Properties.FirstOrDefault(p => string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase));

    private static ReportColumnType ColumnTypeOf(Type propertyType)
    {
        var type = Nullable.GetUnderlyingType(propertyType) ?? propertyType;
        return type switch
        {
            _ when type == typeof(string) => ReportColumnType.Text,
            _ when type == typeof(DateTime) => ReportColumnType.Date,
            _ when type == typeof(bool) => ReportColumnType.Boolean,
            _ when type.IsEnum => ReportColumnType.Enum,
            _ => ReportColumnType.Number,
        };
    }
}

public sealed record GetReportSourcesQuery : IRequest<IReadOnlyList<ReportSourceInfo>>;

internal sealed class GetReportSourcesQueryHandler : IRequestHandler<GetReportSourcesQuery, IReadOnlyList<ReportSourceInfo>>
{
    public Task<IReadOnlyList<ReportSourceInfo>> Handle(GetReportSourcesQuery request, CancellationToken cancellationToken) =>
        Task.FromResult<IReadOnlyList<ReportSourceInfo>>(ReportSourceRegistry.All.Select(s => s.Info).ToList());
}

public sealed record RunReportQuery(ReportDefinition Definition) : IRequest<ReportResult>;

internal sealed class RunReportQueryHandler(
    IApplicationDbContext db,
    ICultureContext culture,
    ICurrentUser currentUser,
    IPermissionService permissions)
    : IRequestHandler<RunReportQuery, ReportResult>
{
    public async Task<ReportResult> Handle(RunReportQuery request, CancellationToken cancellationToken)
    {
        var source = ReportSourceRegistry.Find(request.Definition.Source)
            ?? throw new NotFoundException("ReportSource", request.Definition.Source);

        // A report must never reveal data of a module the user cannot view.
        if (!await permissions.HasPermissionAsync(currentUser.Roles, source.Info.Permission, cancellationToken))
        {
            throw new ForbiddenAccessException();
        }

        return await source.RunAsync(db, request.Definition, culture.IsPersian, cancellationToken);
    }
}
