using Crm.Domain.Inventory;

namespace Crm.Application.Features.Products;

public sealed record ProductListItem(
    Guid Id,
    string Sku,
    string Name,
    LocalizedText? Category,
    decimal UnitPrice,
    string Unit,
    decimal TotalStock,
    decimal LowStockThreshold,
    bool IsActive)
{
    public bool IsLowStock => IsActive && TotalStock <= LowStockThreshold;
}

public sealed record GetProductsQuery : PagedQuery, IRequest<PagedList<ProductListItem>>
{
    public Guid? CategoryId { get; init; }
    public bool LowStockOnly { get; init; }
}

internal sealed class GetProductsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetProductsQuery, PagedList<ProductListItem>>
{
    public Task<PagedList<ProductListItem>> Handle(GetProductsQuery request, CancellationToken cancellationToken)
    {
        var query = db.Products.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(request.Search))
        {
            var term = request.Search.Trim();
            query = query.Where(p => p.Name.Contains(term) || p.Sku.Contains(term));
        }

        if (request.CategoryId is not null)
        {
            query = query.Where(p => p.CategoryId == request.CategoryId);
        }

        if (request.LowStockOnly)
        {
            query = query.Where(p => p.IsActive && p.StockLevels.Sum(s => s.Quantity) <= p.LowStockThreshold);
        }

        return query
            .OrderBy(p => p.Name)
            .Select(p => new ProductListItem(
                p.Id, p.Sku, p.Name, p.Category == null ? null : p.Category.Name, p.UnitPrice, p.Unit,
                p.StockLevels.Sum(s => s.Quantity), p.LowStockThreshold, p.IsActive))
            .ToPagedListAsync(request, cancellationToken);
    }
}

public sealed record ProductStockDto(Guid WarehouseId, string WarehouseName, decimal Quantity);

public sealed record ProductDetailsDto(
    Guid Id,
    string Sku,
    string Name,
    string? Description,
    Guid? CategoryId,
    LocalizedText? Category,
    decimal UnitPrice,
    decimal Cost,
    string Unit,
    decimal LowStockThreshold,
    bool IsActive,
    IReadOnlyList<ProductStockDto> Stock)
{
    public decimal TotalStock => Stock.Sum(s => s.Quantity);
    public bool IsLowStock => IsActive && TotalStock <= LowStockThreshold;
}

public sealed record GetProductDetailsQuery(Guid Id) : IRequest<ProductDetailsDto>;

internal sealed class GetProductDetailsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetProductDetailsQuery, ProductDetailsDto>
{
    public async Task<ProductDetailsDto> Handle(GetProductDetailsQuery request, CancellationToken cancellationToken)
    {
        var product = await db.Products.AsNoTracking()
            .Include(p => p.Category)
            .Include(p => p.StockLevels).ThenInclude(s => s.Warehouse)
            .FirstOrDefaultAsync(p => p.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Product), request.Id);

        return new ProductDetailsDto(
            product.Id, product.Sku, product.Name, product.Description, product.CategoryId, product.Category?.Name,
            product.UnitPrice, product.Cost, product.Unit, product.LowStockThreshold, product.IsActive,
            product.StockLevels
                .Where(s => s.Warehouse is not null)
                .OrderBy(s => s.Warehouse!.Name)
                .Select(s => new ProductStockDto(s.WarehouseId, s.Warehouse!.Name, s.Quantity))
                .ToList());
    }
}

public sealed record GetProductOptionsQuery : IRequest<IReadOnlyList<OptionDto>>;

internal sealed class GetProductOptionsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetProductOptionsQuery, IReadOnlyList<OptionDto>>
{
    public async Task<IReadOnlyList<OptionDto>> Handle(GetProductOptionsQuery request, CancellationToken cancellationToken) =>
        await db.Products.AsNoTracking()
            .Where(p => p.IsActive)
            .OrderBy(p => p.Name)
            .Select(p => new OptionDto(p.Id.ToString(), p.Name + " (" + p.Sku + ")"))
            .ToListAsync(cancellationToken);
}

public sealed class UpsertProductCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string Sku { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public Guid? CategoryId { get; set; }
    public decimal UnitPrice { get; set; }
    public decimal Cost { get; set; }
    public string Unit { get; set; } = "pcs";
    public decimal LowStockThreshold { get; set; }
    public bool IsActive { get; set; } = true;
}

internal sealed class UpsertProductCommandValidator : AbstractValidator<UpsertProductCommand>
{
    public UpsertProductCommandValidator()
    {
        RuleFor(x => x.Sku).NotEmpty().Must(Product.IsValidSku)
            .WithMessage("SKU must be 3-32 characters of A-Z, 0-9 and '-'.");
        RuleFor(x => x.Name).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Description).MaximumLength(2000);
        RuleFor(x => x.Unit).NotEmpty().MaximumLength(16);
        RuleFor(x => x.UnitPrice).GreaterThanOrEqualTo(0);
        RuleFor(x => x.Cost).GreaterThanOrEqualTo(0);
        RuleFor(x => x.LowStockThreshold).GreaterThanOrEqualTo(0);
    }
}

internal sealed class UpsertProductCommandHandler(IApplicationDbContext db) : IRequestHandler<UpsertProductCommand, Guid>
{
    public async Task<Guid> Handle(UpsertProductCommand request, CancellationToken cancellationToken)
    {
        var sku = request.Sku.Trim().ToUpperInvariant();
        if (await db.Products.AnyAsync(p => p.Sku == sku && p.Id != request.Id, cancellationToken))
        {
            throw new AppValidationException(nameof(request.Sku), $"SKU '{sku}' is already in use.");
        }

        Product product;
        if (request.Id is { } id)
        {
            product = await db.Products.FirstOrDefaultAsync(p => p.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(Product), id);
        }
        else
        {
            product = new Product();
            db.Products.Add(product);
        }

        product.SetSku(sku);
        product.Name = request.Name.Trim();
        product.Description = request.Description;
        product.CategoryId = request.CategoryId;
        product.UnitPrice = request.UnitPrice;
        product.Cost = request.Cost;
        product.Unit = request.Unit.Trim();
        product.LowStockThreshold = request.LowStockThreshold;
        product.IsActive = request.IsActive;

        await db.SaveChangesAsync(cancellationToken);
        return product.Id;
    }
}

public sealed record DeleteProductCommand(Guid Id) : IRequest;

internal sealed class DeleteProductCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteProductCommand>
{
    public async Task Handle(DeleteProductCommand request, CancellationToken cancellationToken)
    {
        var product = await db.Products.FirstOrDefaultAsync(p => p.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Product), request.Id);

        if (await db.StockLevels.AnyAsync(s => s.ProductId == request.Id && s.Quantity > 0, cancellationToken))
        {
            throw new DomainException("A product that still has stock cannot be deleted.");
        }

        db.Products.Remove(product);
        await db.SaveChangesAsync(cancellationToken);
    }
}
