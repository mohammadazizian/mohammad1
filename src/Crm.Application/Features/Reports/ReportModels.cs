namespace Crm.Application.Features.Reports;

public enum ReportColumnType
{
    Text,
    Number,
    Date,
    Boolean,
    Enum,
}

public sealed record ReportColumnInfo(string Key, ReportColumnType Type, Type ClrType)
{
    public bool IsNumeric => Type == ReportColumnType.Number;
}

public sealed record ReportSourceInfo(string Key, string Permission, IReadOnlyList<ReportColumnInfo> Columns);

public static class ReportOperators
{
    public const string Equal = "eq";
    public const string NotEqual = "neq";
    public const string Contains = "contains";
    public const string StartsWith = "startswith";
    public const string GreaterThan = "gt";
    public const string GreaterOrEqual = "gte";
    public const string LessThan = "lt";
    public const string LessOrEqual = "lte";

    public static readonly IReadOnlyList<string> All =
        [Equal, NotEqual, Contains, StartsWith, GreaterThan, GreaterOrEqual, LessThan, LessOrEqual];
}

public sealed class ReportFilter
{
    public string Column { get; set; } = string.Empty;
    public string Operator { get; set; } = ReportOperators.Equal;
    public string? Value { get; set; }
}

public enum ReportAggregate
{
    Count,
    Sum,
    Average,
    Min,
    Max,
}

public enum ReportChartType
{
    None,
    Bar,
    Line,
    Pie,
    Doughnut,
}

/// <summary>User-defined report: what to read, how to filter, group and visualize it.</summary>
public sealed class ReportDefinition
{
    public string Source { get; set; } = string.Empty;
    public List<string> Columns { get; set; } = [];
    public List<ReportFilter> Filters { get; set; } = [];
    public string? SortBy { get; set; }
    public bool SortDescending { get; set; }
    public string? GroupBy { get; set; }
    public ReportAggregate Aggregate { get; set; } = ReportAggregate.Count;
    public string? AggregateColumn { get; set; }
    public ReportChartType Chart { get; set; } = ReportChartType.Bar;
}

public sealed record ReportGroup(object? Key, decimal Value, int Count);

public sealed record ReportResult(
    ReportSourceInfo Source,
    ReportDefinition Definition,
    IReadOnlyList<ReportColumnInfo> Columns,
    IReadOnlyList<object?[]> Rows,
    ReportColumnInfo? GroupColumn,
    IReadOnlyList<ReportGroup> Groups,
    bool Truncated);

/// <summary>A fully formatted, display-ready table handed to the exporters.</summary>
public sealed record ReportTable(
    string Title,
    string Subtitle,
    IReadOnlyList<string> Headers,
    IReadOnlyList<IReadOnlyList<object?>> Rows,
    bool RightToLeft);

/// <summary>Renders report tables to downloadable documents.</summary>
public interface IReportExporter
{
    byte[] ToExcel(ReportTable table);
    byte[] ToPdf(ReportTable table);
}
