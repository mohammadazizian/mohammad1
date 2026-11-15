using System.Globalization;
using ClosedXML.Excel;
using Crm.Application.Features.Reports;
using QuestPDF.Drawing;
using QuestPDF.Fluent;
using QuestPDF.Helpers;
using QuestPDF.Infrastructure;

namespace Crm.Infrastructure.Reports;

/// <summary>Excel export through ClosedXML, PDF export through QuestPDF (with RTL / Persian support).</summary>
public sealed class ReportExporter : IReportExporter
{
    private const string FontFamily = "Vazirmatn";

    static ReportExporter()
    {
        // QuestPDF is free for individuals, non-profits and companies under the Community license threshold.
        QuestPDF.Settings.License = LicenseType.Community;

        // The embedded Vazirmatn font covers both Latin and Persian glyphs, so PDFs do not
        // depend on fonts being installed in the container.
        var assembly = typeof(ReportExporter).Assembly;
        foreach (var resource in assembly.GetManifestResourceNames().Where(n => n.EndsWith(".ttf", StringComparison.OrdinalIgnoreCase)))
        {
            using var stream = assembly.GetManifestResourceStream(resource)!;
            FontManager.RegisterFontFromStream(stream);
        }
    }

    public byte[] ToExcel(ReportTable table)
    {
        using var workbook = new XLWorkbook();
        var sheet = workbook.Worksheets.Add("Report");
        sheet.RightToLeft = table.RightToLeft;

        sheet.Cell(1, 1).Value = table.Title;
        sheet.Cell(1, 1).Style.Font.SetBold().Font.SetFontSize(14);
        sheet.Cell(2, 1).Value = table.Subtitle;
        sheet.Cell(2, 1).Style.Font.SetFontColor(XLColor.Gray);

        const int headerRow = 4;
        for (var column = 0; column < table.Headers.Count; column++)
        {
            var cell = sheet.Cell(headerRow, column + 1);
            cell.Value = table.Headers[column];
            cell.Style.Font.SetBold().Fill.SetBackgroundColor(XLColor.FromHtml("#EEF2FF"));
        }

        for (var row = 0; row < table.Rows.Count; row++)
        {
            for (var column = 0; column < table.Rows[row].Count; column++)
            {
                sheet.Cell(headerRow + 1 + row, column + 1).Value = ToCellValue(table.Rows[row][column]);
            }
        }

        if (table.Headers.Count > 0)
        {
            sheet.Range(headerRow, 1, headerRow + table.Rows.Count, table.Headers.Count).SetAutoFilter();
            sheet.SheetView.FreezeRows(headerRow);
            sheet.Columns(1, table.Headers.Count).AdjustToContents(headerRow, headerRow + Math.Min(table.Rows.Count, 200), 8, 60);
        }

        using var stream = new MemoryStream();
        workbook.SaveAs(stream);
        return stream.ToArray();
    }

    public byte[] ToPdf(ReportTable table) =>
        Document.Create(document => document.Page(page =>
        {
            page.Size(PageSizes.A4.Landscape());
            page.Margin(28);
            page.DefaultTextStyle(style => style.FontFamily(FontFamily).FontSize(9));
            if (table.RightToLeft)
            {
                page.ContentFromRightToLeft();
            }

            page.Header().PaddingBottom(10).Column(column =>
            {
                column.Item().Text(table.Title).FontSize(15).Bold();
                column.Item().Text(table.Subtitle).FontSize(8).FontColor(Colors.Grey.Darken1);
            });

            page.Content().Table(grid =>
            {
                grid.ColumnsDefinition(columns =>
                {
                    foreach (var _ in table.Headers)
                    {
                        columns.RelativeColumn();
                    }
                });

                grid.Header(header =>
                {
                    foreach (var title in table.Headers)
                    {
                        header.Cell().Background(Colors.Indigo.Lighten5).BorderBottom(1).BorderColor(Colors.Grey.Lighten1)
                            .Padding(4).Text(title).Bold();
                    }
                });

                foreach (var row in table.Rows)
                {
                    foreach (var value in row)
                    {
                        // Latin-only values (e-mails, phone numbers, SKUs) keep their natural left-to-right
                        // order inside a right-to-left report: wrap them in a Unicode LTR embedding.
                        var text = ToText(value);
                        if (table.RightToLeft && text.Length != 0 && !ContainsRightToLeft(text))
                        {
                            text = $"\u202A{text}\u202C";
                        }

                        grid.Cell().BorderBottom(0.5f).BorderColor(Colors.Grey.Lighten3).Padding(4).Text(text);
                    }
                }
            });

            page.Footer().AlignCenter().Text(text =>
            {
                text.DefaultTextStyle(style => style.FontSize(8).FontColor(Colors.Grey.Darken1));
                text.CurrentPageNumber();
                text.Span(" / ");
                text.TotalPages();
            });
        })).GeneratePdf();

    private static bool ContainsRightToLeft(string text) => text.Any(c => c is >= '\u0590' and <= '\u08FF' or >= '\uFB1D' and <= '\uFEFC');

    private static string ToText(object? value) => value switch
    {
        null => string.Empty,
        decimal number => number.ToString("#,0.##", CultureInfo.InvariantCulture),
        IFormattable formattable => formattable.ToString(null, CultureInfo.InvariantCulture),
        _ => value.ToString() ?? string.Empty,
    };

    private static XLCellValue ToCellValue(object? value) => value switch
    {
        null => Blank.Value,
        decimal number => number,
        int number => number,
        long number => number,
        double number => number,
        bool flag => flag,
        _ => value.ToString(),
    };
}
