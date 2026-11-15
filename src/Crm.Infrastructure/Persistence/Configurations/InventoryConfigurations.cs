using Crm.Domain.Inventory;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Crm.Infrastructure.Persistence.Configurations;

internal sealed class CategoryConfiguration : IEntityTypeConfiguration<Category>
{
    public void Configure(EntityTypeBuilder<Category> builder)
    {
        builder.ComplexProperty(x => x.Name, name =>
        {
            name.Property(n => n.En).HasColumnName("Name").HasMaxLength(100).IsRequired();
            name.Property(n => n.Fa).HasColumnName("NameFa").HasMaxLength(100).IsRequired();
        });
        builder.HasOne(x => x.Parent).WithMany().HasForeignKey(x => x.ParentId);
    }
}

internal sealed class ProductConfiguration : IEntityTypeConfiguration<Product>
{
    public void Configure(EntityTypeBuilder<Product> builder)
    {
        builder.Property(x => x.Sku).HasMaxLength(32).IsRequired();
        builder.Property(x => x.Name).HasMaxLength(200).IsRequired();
        builder.Property(x => x.Description).HasMaxLength(2000);
        builder.Property(x => x.Unit).HasMaxLength(16).IsRequired();

        // A SKU is unique among live products; a soft-deleted product frees its SKU.
        builder.HasIndex(x => x.Sku).IsUnique().HasFilter("[IsDeleted] = 0");
        builder.HasIndex(x => x.Name);
        builder.HasOne(x => x.Category).WithMany(c => c.Products).HasForeignKey(x => x.CategoryId);
        builder.Ignore(x => x.EntityType);
        builder.Ignore(x => x.DisplayName);
    }
}

internal sealed class WarehouseConfiguration : IEntityTypeConfiguration<Warehouse>
{
    public void Configure(EntityTypeBuilder<Warehouse> builder)
    {
        builder.Property(x => x.Code).HasMaxLength(16).IsRequired();
        builder.Property(x => x.Name).HasMaxLength(100).IsRequired();
        builder.Property(x => x.Location).HasMaxLength(200);
        builder.HasIndex(x => x.Code).IsUnique().HasFilter("[IsDeleted] = 0");
    }
}

internal sealed class StockLevelConfiguration : IEntityTypeConfiguration<StockLevel>
{
    public void Configure(EntityTypeBuilder<StockLevel> builder)
    {
        builder.HasIndex(x => new { x.ProductId, x.WarehouseId }).IsUnique();
        builder.HasOne(x => x.Product).WithMany(p => p.StockLevels).HasForeignKey(x => x.ProductId);
        builder.HasOne(x => x.Warehouse).WithMany().HasForeignKey(x => x.WarehouseId);

        // Optimistic concurrency: two simultaneous movements can never both spend the same stock.
        builder.Property<byte[]>("RowVersion").IsRowVersion();
        builder.ToTable(t => t.HasCheckConstraint("CK_StockLevels_Quantity_NonNegative", "[Quantity] >= 0"));
    }
}

internal sealed class InventoryTransactionConfiguration : IEntityTypeConfiguration<InventoryTransaction>
{
    public void Configure(EntityTypeBuilder<InventoryTransaction> builder)
    {
        builder.Property(x => x.Number).HasMaxLength(32).IsRequired();
        builder.Property(x => x.Reference).HasMaxLength(64);
        builder.Property(x => x.Note).HasMaxLength(1000);
        builder.HasIndex(x => x.Number).IsUnique();
        builder.HasIndex(x => x.OccurredAt);
        builder.HasOne(x => x.Product).WithMany().HasForeignKey(x => x.ProductId);
        builder.HasOne(x => x.FromWarehouse).WithMany().HasForeignKey(x => x.FromWarehouseId);
        builder.HasOne(x => x.ToWarehouse).WithMany().HasForeignKey(x => x.ToWarehouseId);
        builder.Ignore(x => x.EntityType);
        builder.Ignore(x => x.DisplayName);
    }
}
