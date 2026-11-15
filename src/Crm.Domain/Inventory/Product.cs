using System.Text.RegularExpressions;
using Crm.Domain.Common;

namespace Crm.Domain.Inventory;

public class Category : AuditableEntity
{
    public LocalizedText Name { get; set; } = new();
    public Guid? ParentId { get; set; }
    public Category? Parent { get; set; }
    public ICollection<Product> Products { get; } = [];
}

public partial class Product : AuditableEntity, ITrackableEntity
{
    public string Sku { get; private set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public Guid? CategoryId { get; set; }
    public Category? Category { get; set; }
    public decimal UnitPrice { get; set; }
    public decimal Cost { get; set; }
    public string Unit { get; set; } = "pcs";

    /// <summary>Total quantity (across warehouses) at or below which a low-stock alert is raised.</summary>
    public decimal LowStockThreshold { get; set; }
    public bool IsActive { get; set; } = true;

    public ICollection<StockLevel> StockLevels { get; } = [];

    public TrackableEntityType EntityType => TrackableEntityType.Product;
    public string DisplayName => $"{Name} ({Sku})";

    /// <summary>SKU rule: 3-32 chars, upper-case letters, digits and dashes.</summary>
    public void SetSku(string sku)
    {
        var normalized = (sku ?? string.Empty).Trim().ToUpperInvariant();
        if (!IsValidSku(normalized))
        {
            throw new DomainException("SKU must be 3-32 characters of A-Z, 0-9 and '-'.");
        }

        Sku = normalized;
    }

    public static bool IsValidSku(string? sku) => sku is not null && SkuPattern().IsMatch(sku.Trim().ToUpperInvariant());

    [GeneratedRegex("^[A-Z0-9][A-Z0-9-]{2,31}$")]
    private static partial Regex SkuPattern();
}

public class Warehouse : AuditableEntity
{
    public string Code { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Location { get; set; }
    public bool IsActive { get; set; } = true;
}
