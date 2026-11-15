using Crm.Application.Common.Behaviors;
using Crm.Application.Common.Security;
using Crm.Domain.Collaboration;
using Crm.Domain.Inventory;

namespace Crm.Application.Features.Inventory;

public sealed record InventoryTransactionDto(
    Guid Id,
    string Number,
    StockMovementType Type,
    Guid ProductId,
    string ProductName,
    string ProductSku,
    string? FromWarehouse,
    string? ToWarehouse,
    decimal Quantity,
    string Unit,
    string? Reference,
    string? Note,
    DateTime OccurredAt);

public sealed record GetInventoryTransactionsQuery : PagedQuery, IRequest<PagedList<InventoryTransactionDto>>
{
    public StockMovementType? Type { get; init; }
    public Guid? ProductId { get; init; }
}

internal sealed class GetInventoryTransactionsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetInventoryTransactionsQuery, PagedList<InventoryTransactionDto>>
{
    public Task<PagedList<InventoryTransactionDto>> Handle(GetInventoryTransactionsQuery request, CancellationToken cancellationToken)
    {
        var query = db.InventoryTransactions.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(request.Search))
        {
            var term = request.Search.Trim();
            query = query.Where(t => t.Number.Contains(term) || t.Reference!.Contains(term)
                                     || t.Product!.Name.Contains(term) || t.Product.Sku.Contains(term));
        }

        if (request.Type is not null)
        {
            query = query.Where(t => t.Type == request.Type);
        }

        if (request.ProductId is not null)
        {
            query = query.Where(t => t.ProductId == request.ProductId);
        }

        return query.OrderByDescending(t => t.OccurredAt)
            .Select(InventoryMapping.ToDto)
            .ToPagedListAsync(request, cancellationToken);
    }
}

public sealed record GetInventoryTransactionQuery(Guid Id) : IRequest<InventoryTransactionDto>;

internal sealed class GetInventoryTransactionQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetInventoryTransactionQuery, InventoryTransactionDto>
{
    public async Task<InventoryTransactionDto> Handle(GetInventoryTransactionQuery request, CancellationToken cancellationToken) =>
        await db.InventoryTransactions.AsNoTracking()
            .Where(t => t.Id == request.Id)
            .Select(InventoryMapping.ToDto)
            .FirstOrDefaultAsync(cancellationToken)
        ?? throw new NotFoundException(nameof(InventoryTransaction), request.Id);
}

internal static class InventoryMapping
{
    public static readonly System.Linq.Expressions.Expression<Func<InventoryTransaction, InventoryTransactionDto>> ToDto =
        t => new InventoryTransactionDto(
            t.Id, t.Number, t.Type, t.ProductId, t.Product!.Name, t.Product.Sku,
            t.FromWarehouse == null ? null : t.FromWarehouse.Name,
            t.ToWarehouse == null ? null : t.ToWarehouse.Name,
            t.Quantity, t.Product.Unit, t.Reference, t.Note, t.OccurredAt);
}

/// <summary>Registers a stock movement and updates the affected stock levels atomically.</summary>
public sealed class CreateInventoryTransactionCommand : IRequest<Guid>
{
    public StockMovementType Type { get; set; } = StockMovementType.In;
    public Guid ProductId { get; set; }
    public Guid? FromWarehouseId { get; set; }
    public Guid? ToWarehouseId { get; set; }
    public decimal Quantity { get; set; } = 1;
    public string? Reference { get; set; }
    public string? Note { get; set; }
}

internal sealed class CreateInventoryTransactionCommandValidator : AbstractValidator<CreateInventoryTransactionCommand>
{
    public CreateInventoryTransactionCommandValidator()
    {
        RuleFor(x => x.Type).IsInEnum();
        RuleFor(x => x.ProductId).NotEmpty();
        RuleFor(x => x.Quantity).GreaterThan(0);
        RuleFor(x => x.Reference).MaximumLength(64);
        RuleFor(x => x.Note).MaximumLength(1000);
        RuleFor(x => x.FromWarehouseId).NotEmpty().When(x => x.Type is StockMovementType.Out or StockMovementType.Transfer);
        RuleFor(x => x.ToWarehouseId).NotEmpty().When(x => x.Type is StockMovementType.In or StockMovementType.Transfer);
        RuleFor(x => x.ToWarehouseId).NotEqual(x => x.FromWarehouseId).When(x => x.Type == StockMovementType.Transfer);
    }
}

internal sealed class CreateInventoryTransactionCommandHandler(IApplicationDbContext db, TimeProvider clock)
    : IRequestHandler<CreateInventoryTransactionCommand, Guid>
{
    public async Task<Guid> Handle(CreateInventoryTransactionCommand request, CancellationToken cancellationToken)
    {
        if (!await db.Products.AnyAsync(p => p.Id == request.ProductId, cancellationToken))
        {
            throw new NotFoundException(nameof(Product), request.ProductId);
        }

        var now = clock.GetUtcNow().UtcDateTime;
        var transaction = InventoryTransaction.Create(
            request.Type, request.ProductId, request.FromWarehouseId, request.ToWarehouseId,
            request.Quantity, request.Reference?.Trim(), request.Note, now);

        if (transaction.FromWarehouseId is { } fromId)
        {
            var source = await GetOrCreateLevelAsync(request.ProductId, fromId, cancellationToken);
            source.Decrease(request.Quantity, now);
        }

        if (transaction.ToWarehouseId is { } toId)
        {
            var target = await GetOrCreateLevelAsync(request.ProductId, toId, cancellationToken);
            target.Increase(request.Quantity, now);
        }

        db.InventoryTransactions.Add(transaction);
        await db.SaveChangesAsync(cancellationToken);
        return transaction.Id;
    }

    private async Task<StockLevel> GetOrCreateLevelAsync(Guid productId, Guid warehouseId, CancellationToken cancellationToken)
    {
        if (!await db.Warehouses.AnyAsync(w => w.Id == warehouseId, cancellationToken))
        {
            throw new NotFoundException(nameof(Warehouse), warehouseId);
        }

        var level = await db.StockLevels
            .FirstOrDefaultAsync(s => s.ProductId == productId && s.WarehouseId == warehouseId, cancellationToken);
        if (level is null)
        {
            level = new StockLevel { ProductId = productId, WarehouseId = warehouseId };
            db.StockLevels.Add(level);
        }

        return level;
    }
}

/// <summary>Low-stock threshold alert: notifies everyone allowed to see the inventory.</summary>
internal sealed class StockChangedEventHandler(
    IApplicationDbContext db,
    IIdentityService identity,
    INotificationService notifications)
    : INotificationHandler<DomainEventNotification<StockChangedEvent>>
{
    public async Task Handle(DomainEventNotification<StockChangedEvent> notification, CancellationToken cancellationToken)
    {
        var productId = notification.Event.ProductId;
        var product = await db.Products.AsNoTracking()
            .Where(p => p.Id == productId && p.IsActive)
            .Select(p => new { p.Name, p.Sku, p.Unit, p.LowStockThreshold, Total = p.StockLevels.Sum(s => s.Quantity) })
            .FirstOrDefaultAsync(cancellationToken);

        if (product is null || product.Total > product.LowStockThreshold)
        {
            return;
        }

        var recipients = await identity.GetUserIdsWithPermissionAsync(
            Permissions.For(Permissions.Modules.Inventory, Permissions.Actions.View), cancellationToken);

        // Do not repeat an alert the user has not read yet.
        var alreadyAlerted = await db.Notifications.AsNoTracking()
            .Where(n => n.Type == NotificationType.LowStock && n.EntityId == productId && !n.IsRead)
            .Select(n => n.UserId)
            .ToListAsync(cancellationToken);

        await notifications.NotifyAsync(
            recipients.Except(alreadyAlerted),
            NotificationType.LowStock,
            $"{product.Name} ({product.Sku}): {product.Total:0.##} {product.Unit}",
            new EntityRef(TrackableEntityType.Product, productId),
            cancellationToken);
    }
}
