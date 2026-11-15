using System.Globalization;
using System.Text.Json;
using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.Application.Features.Reports;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Reports;

[HasPermission(Permissions.Modules.Reports, Permissions.Actions.View)]
public class IndexModel(IReportExporter exporter, ICultureContext culture, IPermissionService permissions, ICurrentUser currentUser)
    : AppPageModel
{
    public const int FilterSlots = 3;
    private const int PreviewRows = 200;

    private static readonly string[] PersianGregorianMonths =
        ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن", "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"];

    [BindProperty]
    public ReportDefinition Definition { get; set; } = new();

    /// <summary>The data sets the current user is allowed to report on.</summary>
    public IReadOnlyList<ReportSourceInfo> Sources { get; private set; } = [];

    public ReportSourceInfo Source { get; private set; } = default!;

    public ReportResult? Result { get; private set; }

    public int PreviewLimit => PreviewRows;

    public async Task<IActionResult> OnGetAsync(string? source)
    {
        if (!await LoadSourcesAsync(source))
        {
            return Forbid();
        }

        Definition = new ReportDefinition { Source = Source.Key, Columns = Source.Columns.Take(6).Select(c => c.Key).ToList() };
        return Page();
    }

    /// <summary>htmx: the column / filter / grouping options of the chosen data set.</summary>
    public async Task<IActionResult> OnGetBuilderAsync(string source)
    {
        if (!await LoadSourcesAsync(source))
        {
            return Forbid();
        }

        Definition = new ReportDefinition { Source = Source.Key, Columns = Source.Columns.Take(6).Select(c => c.Key).ToList() };
        return Partial("_BuilderPartial", this);
    }

    /// <summary>htmx: runs the report and returns chart + table.</summary>
    public async Task<IActionResult> OnPostRunAsync()
    {
        Result = await Mediator.Send(new RunReportQuery(Definition));
        return Partial("_ResultPartial", this);
    }

    public async Task<IActionResult> OnPostExportAsync(string format)
    {
        Result = await Mediator.Send(new RunReportQuery(Definition));
        var table = BuildTable(Result, forExcel: format == "xlsx");
        var fileName = $"{Result.Source.Key}-{DateTime.UtcNow:yyyyMMdd-HHmm}";

        return format == "xlsx"
            ? File(exporter.ToExcel(table), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fileName + ".xlsx")
            : File(exporter.ToPdf(table), "application/pdf", fileName + ".pdf");
    }

    // ---- Presentation helpers (used by the partials and the exporters) ---------------------

    public string SourceLabel(ReportSourceInfo source) => L.Field(source.Key);

    public string ColumnLabel(ReportColumnInfo column) => L.Field(column.Key);

    public string Format(ReportColumnInfo column, object? value) => value switch
    {
        null => string.Empty,
        Enum member => L.EnumName(member.GetType(), member.ToString()),
        DateTime date => Formatter.Date(date),
        bool flag => L[flag ? "Yes" : "No"],
        decimal number => Formatter.Number(number),
        IConvertible number when column.IsNumeric => Formatter.Number(Convert.ToDecimal(number, CultureInfo.InvariantCulture)),
        _ => value.ToString() ?? string.Empty,
    };

    /// <summary>Label of a group: dates are grouped per (Gregorian) month.</summary>
    public string FormatGroupKey(ReportColumnInfo column, object? key) => key switch
    {
        null => L["(empty)"],
        DateTime month => culture.IsPersian
            ? $"{PersianGregorianMonths[month.Month - 1]} {Formatter.Number(month.Year).Replace("٬", string.Empty)}"
            : month.ToString("MMM yyyy", CultureInfo.InvariantCulture),
        _ => Format(column, key),
    };

    public string AggregateLabel(ReportResult result) =>
        result.Definition.Aggregate == ReportAggregate.Count || string.IsNullOrEmpty(result.Definition.AggregateColumn)
            ? L.Enum(ReportAggregate.Count)
            : $"{L.Enum(result.Definition.Aggregate)} · {L.Field(result.Definition.AggregateColumn)}";

    public string ChartJson(ReportResult result) => JsonSerializer.Serialize(new
    {
        type = result.Definition.Chart.ToString().ToLowerInvariant(),
        label = AggregateLabel(result),
        labels = result.Groups.Select(g => FormatGroupKey(result.GroupColumn!, g.Key)),
        values = result.Groups.Select(g => g.Value),
    });

    private ReportTable BuildTable(ReportResult result, bool forExcel)
    {
        // Excel keeps real numbers (so they stay summable); everything else is display text.
        object? Cell(ReportColumnInfo column, object? value) =>
            forExcel && column.IsNumeric && value is not null ? Convert.ToDecimal(value, CultureInfo.InvariantCulture) : Format(column, value);

        var rows = result.Rows
            .Select(row => (IReadOnlyList<object?>)row.Select((value, index) => Cell(result.Columns[index], value)).ToList())
            .ToList();

        return new ReportTable(
            SourceLabel(result.Source),
            $"{Formatter.DateTime(DateTime.UtcNow)} · {L["{0} items", Formatter.Number(rows.Count)]}",
            result.Columns.Select(ColumnLabel).ToList(),
            rows,
            culture.IsRtl);
    }

    private async Task<bool> LoadSourcesAsync(string? requested)
    {
        var all = await Mediator.Send(new GetReportSourcesQuery());
        var allowed = new List<ReportSourceInfo>();
        foreach (var source in all)
        {
            if (await permissions.HasPermissionAsync(currentUser.Roles, source.Permission))
            {
                allowed.Add(source);
            }
        }

        Sources = allowed;
        Source = allowed.FirstOrDefault(s => string.Equals(s.Key, requested, StringComparison.OrdinalIgnoreCase)) ?? allowed.FirstOrDefault()!;
        return Source is not null;
    }
}
