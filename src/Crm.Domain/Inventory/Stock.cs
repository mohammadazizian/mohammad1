using Crm.Domain.Common;

namespace Crm.Domain.Inventory;

/// <summary>On-hand quantity of one product in one warehouse.</summary>
public class StockLevel : BaseEntity
{
    public Guid ProductId { get; set; }
    public Product? Product { get; set; }
    public Guid WarehouseId { get; set; }
    public Warehouse? Warehouse { get; set; }
    public decimal Quantity { get; private set; }
    public DateTime UpdatedAt { get; private set; }

    public void Increase(decimal quantity, DateTime utcNow)
    {
        Quantity += quantity;
        UpdatedAt = utcNow;
    }

    public void Decrease(decimal quantity, DateTime utcNow)
    {
        if (quantity > Quantity)
        {
            throw new DomainException($"Insufficient stock: {Quantity:0.##} available, {quantity:0.##} requested.");
        }

        Quantity -= quantity;
        UpdatedAt = utcNow;
    }
}

public enum StockMovementType
{
    In = 1,
    Out = 2,
    Transfer = 3,
}

/// <summary>An immutable stock movement (in / out / transfer) - a first-class trackable object.</summary>
public class InventoryTransaction : AuditableEntity, ITrackableEntity
{
    private InventoryTransaction()
    {
    }

    public string Number { get; private set; } = string.Empty;
    public StockMovementType Type { get; private set; }
    public Guid ProductId { get; private set; }
    public Product? Product { get; private set; }
    public Guid? FromWarehouseId { get; private set; }
    public Warehouse? FromWarehouse { get; private set; }
    public Guid? ToWarehouseId { get; private set; }
    public Warehouse? ToWarehouse { get; private set; }
    public decimal Quantity { get; private set; }
    public string? Reference { get; private set; }
    public string? Note { get; private set; }
    public DateTime OccurredAt { get; private set; }

    public TrackableEntityType EntityType => TrackableEntityType.InventoryTransaction;
    public string DisplayName => Number;

    public static InventoryTransaction Create(
        StockMovementType type,
        Guid productId,
        Guid? fromWarehouseId,
        Guid? toWarehouseId,
        decimal quantity,
        string? reference,
        string? note,
        DateTime utcNow)
    {
        if (quantity <= 0)
        {
            throw new DomainException("Quantity must be greater than zero.");
        }

        var needsSource = type is StockMovementType.Out or StockMovementType.Transfer;
        var needsTarget = type is StockMovementType.In or StockMovementType.Transfer;

        if (needsSource && fromWarehouseId is null)
        {
            throw new DomainException("A source warehouse is required.");
        }

        if (needsTarget && toWarehouseId is null)
        {
            throw new DomainException("A destination warehouse is required.");
        }

        if (type == StockMovementType.Transfer && fromWarehouseId == toWarehouseId)
        {
            throw new DomainException("Source and destination warehouses must differ.");
        }

        var transaction = new InventoryTransaction
        {
            Type = type,
            ProductId = productId,
            FromWarehouseId = needsSource ? fromWarehouseId : null,
            ToWarehouseId = needsTarget ? toWarehouseId : null,
            Quantity = quantity,
            Reference = reference,
            Note = note,
            OccurredAt = utcNow,
        };
        transaction.Number = $"TRX-{utcNow:yyMMdd}-{transaction.Id.ToString("N")[^6..].ToUpperInvariant()}";
        transaction.AddDomainEvent(new StockChangedEvent(productId));
        return transaction;
    }
}

/// <summary>Raised whenever the stock of a product changes; drives low-stock alerts.</summary>
public sealed record StockChangedEvent(Guid ProductId) : IDomainEvent;
