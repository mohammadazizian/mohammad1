using Crm.Domain.Sales;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Crm.Infrastructure.Persistence.Configurations;

internal sealed class CustomerConfiguration : IEntityTypeConfiguration<Customer>
{
    public void Configure(EntityTypeBuilder<Customer> builder)
    {
        builder.Property(x => x.Name).HasMaxLength(200).IsRequired();
        builder.Property(x => x.Email).HasMaxLength(256);
        builder.Property(x => x.Phone).HasMaxLength(32);
        builder.Property(x => x.TaxId).HasMaxLength(32);
        builder.Property(x => x.Notes).HasMaxLength(2000);
        builder.HasIndex(x => x.Name);

        // Value object stored inline (Address_Street, Address_City, ...).
        builder.ComplexProperty(x => x.Address, address =>
        {
            address.Property(a => a.Street).HasMaxLength(300);
            address.Property(a => a.City).HasMaxLength(100);
            address.Property(a => a.Country).HasMaxLength(100);
            address.Property(a => a.PostalCode).HasMaxLength(20);
        });

        builder.Ignore(x => x.EntityType);
        builder.Ignore(x => x.DisplayName);
    }
}

internal sealed class ContactConfiguration : IEntityTypeConfiguration<Contact>
{
    public void Configure(EntityTypeBuilder<Contact> builder)
    {
        builder.Property(x => x.FirstName).HasMaxLength(100).IsRequired();
        builder.Property(x => x.LastName).HasMaxLength(100);
        builder.Property(x => x.Email).HasMaxLength(256);
        builder.Property(x => x.Phone).HasMaxLength(32);
        builder.Property(x => x.Position).HasMaxLength(100);
        builder.Ignore(x => x.FullName);
        builder.HasOne(x => x.Customer).WithMany(c => c.Contacts).HasForeignKey(x => x.CustomerId);
    }
}

internal sealed class InteractionConfiguration : IEntityTypeConfiguration<Interaction>
{
    public void Configure(EntityTypeBuilder<Interaction> builder)
    {
        builder.Property(x => x.Subject).HasMaxLength(200).IsRequired();
        builder.Property(x => x.Notes).HasMaxLength(4000);
        builder.Property(x => x.UserName).HasMaxLength(256);
        builder.HasOne(x => x.Customer).WithMany(c => c.Interactions).HasForeignKey(x => x.CustomerId);
    }
}

internal sealed class LeadConfiguration : IEntityTypeConfiguration<Lead>
{
    public void Configure(EntityTypeBuilder<Lead> builder)
    {
        builder.Property(x => x.Name).HasMaxLength(200).IsRequired();
        builder.Property(x => x.Company).HasMaxLength(200);
        builder.Property(x => x.Email).HasMaxLength(256);
        builder.Property(x => x.Phone).HasMaxLength(32);
        builder.Property(x => x.Notes).HasMaxLength(4000);
        builder.HasIndex(x => x.Status);
        builder.Ignore(x => x.EntityType);
        builder.Ignore(x => x.DisplayName);
    }
}

internal sealed class PipelineConfiguration : IEntityTypeConfiguration<Pipeline>
{
    public void Configure(EntityTypeBuilder<Pipeline> builder)
    {
        builder.Property(x => x.Name).HasMaxLength(100).IsRequired();
    }
}

internal sealed class PipelineStageConfiguration : IEntityTypeConfiguration<PipelineStage>
{
    public void Configure(EntityTypeBuilder<PipelineStage> builder)
    {
        builder.ComplexProperty(x => x.Name, name =>
        {
            name.Property(n => n.En).HasColumnName("Name").HasMaxLength(100).IsRequired();
            name.Property(n => n.Fa).HasColumnName("NameFa").HasMaxLength(100).IsRequired();
        });
        builder.Ignore(x => x.IsClosed);
        builder.HasOne(x => x.Pipeline).WithMany(p => p.Stages).HasForeignKey(x => x.PipelineId);
    }
}

internal sealed class DealConfiguration : IEntityTypeConfiguration<Deal>
{
    public void Configure(EntityTypeBuilder<Deal> builder)
    {
        builder.Property(x => x.Title).HasMaxLength(200).IsRequired();
        builder.Property(x => x.Notes).HasMaxLength(4000);
        builder.HasOne(x => x.Customer).WithMany(c => c.Deals).HasForeignKey(x => x.CustomerId);
        builder.HasOne(x => x.Pipeline).WithMany().HasForeignKey(x => x.PipelineId);
        builder.HasOne(x => x.Stage).WithMany().HasForeignKey(x => x.StageId);
        builder.Ignore(x => x.EntityType);
        builder.Ignore(x => x.DisplayName);
    }
}
