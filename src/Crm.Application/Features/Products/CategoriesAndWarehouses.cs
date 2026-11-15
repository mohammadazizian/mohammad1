using Crm.Domain.Inventory;

namespace Crm.Application.Features.Products;

public sealed record CategoryDto(Guid Id, LocalizedText Name, int ProductCount);

public sealed record GetCategoriesQuery : IRequest<IReadOnlyList<CategoryDto>>;

internal sealed class GetCategoriesQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetCategoriesQuery, IReadOnlyList<CategoryDto>>
{
    public async Task<IReadOnlyList<CategoryDto>> Handle(GetCategoriesQuery request, CancellationToken cancellationToken) =>
        await db.Categories.AsNoTracking()
            .OrderBy(c => c.Name.En)
            .Select(c => new CategoryDto(c.Id, c.Name, c.Products.Count))
            .ToListAsync(cancellationToken);
}

public sealed class UpsertCategoryCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string NameEn { get; set; } = string.Empty;
    public string NameFa { get; set; } = string.Empty;
}

internal sealed class UpsertCategoryCommandValidator : AbstractValidator<UpsertCategoryCommand>
{
    public UpsertCategoryCommandValidator()
    {
        RuleFor(x => x.NameEn).NotEmpty().MaximumLength(100);
        RuleFor(x => x.NameFa).MaximumLength(100);
    }
}

internal sealed class UpsertCategoryCommandHandler(IApplicationDbContext db) : IRequestHandler<UpsertCategoryCommand, Guid>
{
    public async Task<Guid> Handle(UpsertCategoryCommand request, CancellationToken cancellationToken)
    {
        Category category;
        if (request.Id is { } id)
        {
            category = await db.Categories.FirstOrDefaultAsync(c => c.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(Category), id);
        }
        else
        {
            category = new Category();
            db.Categories.Add(category);
        }

        category.Name = new LocalizedText(request.NameEn.Trim(), request.NameFa?.Trim() ?? string.Empty);
        await db.SaveChangesAsync(cancellationToken);
        return category.Id;
    }
}

public sealed record DeleteCategoryCommand(Guid Id) : IRequest;

internal sealed class DeleteCategoryCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteCategoryCommand>
{
    public async Task Handle(DeleteCategoryCommand request, CancellationToken cancellationToken)
    {
        var category = await db.Categories.FirstOrDefaultAsync(c => c.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Category), request.Id);

        if (await db.Products.AnyAsync(p => p.CategoryId == request.Id, cancellationToken))
        {
            throw new DomainException("A category that still contains products cannot be deleted.");
        }

        db.Categories.Remove(category);
        await db.SaveChangesAsync(cancellationToken);
    }
}

public sealed record WarehouseDto(Guid Id, string Code, string Name, string? Location, bool IsActive, decimal TotalQuantity);

public sealed record GetWarehousesQuery : IRequest<IReadOnlyList<WarehouseDto>>;

internal sealed class GetWarehousesQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetWarehousesQuery, IReadOnlyList<WarehouseDto>>
{
    public async Task<IReadOnlyList<WarehouseDto>> Handle(GetWarehousesQuery request, CancellationToken cancellationToken) =>
        await db.Warehouses.AsNoTracking()
            .OrderBy(w => w.Code)
            .Select(w => new WarehouseDto(
                w.Id, w.Code, w.Name, w.Location, w.IsActive,
                db.StockLevels.Where(s => s.WarehouseId == w.Id).Sum(s => s.Quantity)))
            .ToListAsync(cancellationToken);
}

public sealed class UpsertWarehouseCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string Code { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Location { get; set; }
}

internal sealed class UpsertWarehouseCommandValidator : AbstractValidator<UpsertWarehouseCommand>
{
    public UpsertWarehouseCommandValidator()
    {
        RuleFor(x => x.Code).NotEmpty().MaximumLength(16);
        RuleFor(x => x.Name).NotEmpty().MaximumLength(100);
        RuleFor(x => x.Location).MaximumLength(200);
    }
}

internal sealed class UpsertWarehouseCommandHandler(IApplicationDbContext db) : IRequestHandler<UpsertWarehouseCommand, Guid>
{
    public async Task<Guid> Handle(UpsertWarehouseCommand request, CancellationToken cancellationToken)
    {
        var code = request.Code.Trim().ToUpperInvariant();
        if (await db.Warehouses.AnyAsync(w => w.Code == code && w.Id != request.Id, cancellationToken))
        {
            throw new AppValidationException(nameof(request.Code), $"Warehouse code '{code}' is already in use.");
        }

        Warehouse warehouse;
        if (request.Id is { } id)
        {
            warehouse = await db.Warehouses.FirstOrDefaultAsync(w => w.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(Warehouse), id);
        }
        else
        {
            warehouse = new Warehouse();
            db.Warehouses.Add(warehouse);
        }

        warehouse.Code = code;
        warehouse.Name = request.Name.Trim();
        warehouse.Location = request.Location;
        await db.SaveChangesAsync(cancellationToken);
        return warehouse.Id;
    }
}

public sealed record DeleteWarehouseCommand(Guid Id) : IRequest;

internal sealed class DeleteWarehouseCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteWarehouseCommand>
{
    public async Task Handle(DeleteWarehouseCommand request, CancellationToken cancellationToken)
    {
        var warehouse = await db.Warehouses.FirstOrDefaultAsync(w => w.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Warehouse), request.Id);

        if (await db.StockLevels.AnyAsync(s => s.WarehouseId == request.Id && s.Quantity > 0, cancellationToken))
        {
            throw new DomainException("A warehouse that still holds stock cannot be deleted.");
        }

        db.Warehouses.Remove(warehouse);
        await db.SaveChangesAsync(cancellationToken);
    }
}
