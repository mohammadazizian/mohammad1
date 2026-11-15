using Crm.Application.Common.Security;
using Crm.Domain.Collaboration;
using Crm.Domain.Inventory;
using Crm.Domain.Sales;

namespace Crm.Application.Features.Reports;

// Flat row shapes of the reportable data sets. Every public property becomes a selectable,
// filterable and groupable column - adding a column or a source needs no other change.

public sealed class CustomerReportRow
{
    public string Name { get; set; } = string.Empty;
    public CustomerType Type { get; set; }
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public string? City { get; set; }
    public string? Country { get; set; }
    public int OpenDeals { get; set; }
    public DateTime CreatedAt { get; set; }
}

public sealed class LeadReportRow
{
    public string Name { get; set; } = string.Empty;
    public string? Company { get; set; }
    public LeadSource Source { get; set; }
    public LeadStatus Status { get; set; }
    public decimal EstimatedValue { get; set; }
    public DateTime CreatedAt { get; set; }
}

public sealed class DealReportRow
{
    public string Title { get; set; } = string.Empty;
    public string Customer { get; set; } = string.Empty;
    public string Stage { get; set; } = string.Empty;
    public decimal Amount { get; set; }
    public int Probability { get; set; }
    public DateTime? ExpectedCloseDate { get; set; }
    public DateTime? ClosedAt { get; set; }
    public DateTime CreatedAt { get; set; }
}

public sealed class ProductReportRow
{
    public string Sku { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Category { get; set; }
    public decimal UnitPrice { get; set; }
    public decimal Cost { get; set; }
    public decimal Stock { get; set; }
    public decimal LowStockThreshold { get; set; }
    public bool IsActive { get; set; }
}

public sealed class StockMovementReportRow
{
    public string Number { get; set; } = string.Empty;
    public StockMovementType Type { get; set; }
    public string Product { get; set; } = string.Empty;
    public string Sku { get; set; } = string.Empty;
    public string? FromWarehouse { get; set; }
    public string? ToWarehouse { get; set; }
    public decimal Quantity { get; set; }
    public DateTime OccurredAt { get; set; }
}

public sealed class TaskReportRow
{
    public string Title { get; set; } = string.Empty;
    public TaskItemStatus Status { get; set; }
    public TaskPriority Priority { get; set; }
    public string? AssignedTo { get; set; }
    public string? RelatedTo { get; set; }
    public DateTime? DueAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public DateTime CreatedAt { get; set; }
}

internal static class ReportSourceRegistry
{
    private static readonly IReadOnlyList<IReportSource> Sources =
    [
        new ReportSource<CustomerReportRow>("Customers", Permissions.Modules.Customers, (db, _) =>
            db.Customers.AsNoTracking().Select(c => new CustomerReportRow
            {
                Name = c.Name,
                Type = c.Type,
                Email = c.Email,
                Phone = c.Phone,
                City = c.Address.City,
                Country = c.Address.Country,
                OpenDeals = c.Deals.Count(d => d.ClosedAt == null),
                CreatedAt = c.CreatedAt,
            })),
        new ReportSource<LeadReportRow>("Leads", Permissions.Modules.Leads, (db, _) =>
            db.Leads.AsNoTracking().Select(l => new LeadReportRow
            {
                Name = l.Name,
                Company = l.Company,
                Source = l.Source,
                Status = l.Status,
                EstimatedValue = l.EstimatedValue,
                CreatedAt = l.CreatedAt,
            })),
        new ReportSource<DealReportRow>("Deals", Permissions.Modules.Deals, (db, persian) =>
            db.Deals.AsNoTracking().Select(d => new DealReportRow
            {
                Title = d.Title,
                Customer = d.Customer!.Name,
                Stage = persian && d.Stage!.Name.Fa != "" ? d.Stage.Name.Fa : d.Stage!.Name.En,
                Amount = d.Amount,
                Probability = d.Stage.Probability,
                ExpectedCloseDate = d.ExpectedCloseDate,
                ClosedAt = d.ClosedAt,
                CreatedAt = d.CreatedAt,
            })),
        new ReportSource<ProductReportRow>("Products", Permissions.Modules.Products, (db, persian) =>
            db.Products.AsNoTracking().Select(p => new ProductReportRow
            {
                Sku = p.Sku,
                Name = p.Name,
                Category = p.Category == null ? null : persian && p.Category.Name.Fa != "" ? p.Category.Name.Fa : p.Category.Name.En,
                UnitPrice = p.UnitPrice,
                Cost = p.Cost,
                Stock = p.StockLevels.Sum(s => s.Quantity),
                LowStockThreshold = p.LowStockThreshold,
                IsActive = p.IsActive,
            })),
        new ReportSource<StockMovementReportRow>("StockMovements", Permissions.Modules.Inventory, (db, _) =>
            db.InventoryTransactions.AsNoTracking().Select(t => new StockMovementReportRow
            {
                Number = t.Number,
                Type = t.Type,
                Product = t.Product!.Name,
                Sku = t.Product.Sku,
                FromWarehouse = t.FromWarehouse == null ? null : t.FromWarehouse.Name,
                ToWarehouse = t.ToWarehouse == null ? null : t.ToWarehouse.Name,
                Quantity = t.Quantity,
                OccurredAt = t.OccurredAt,
            })),
        new ReportSource<TaskReportRow>("Tasks", Permissions.Modules.Tasks, (db, _) =>
            db.Tasks.AsNoTracking().Select(t => new TaskReportRow
            {
                Title = t.Title,
                Status = t.Status,
                Priority = t.Priority,
                AssignedTo = t.AssignedToUserName ?? t.AssignedToRole,
                RelatedTo = t.EntityDisplayName,
                DueAt = t.DueAt,
                CompletedAt = t.CompletedAt,
                CreatedAt = t.CreatedAt,
            })),
    ];

    public static IReadOnlyList<IReportSource> All => Sources;

    public static IReportSource? Find(string? key) =>
        Sources.FirstOrDefault(s => string.Equals(s.Info.Key, key, StringComparison.OrdinalIgnoreCase));
}
