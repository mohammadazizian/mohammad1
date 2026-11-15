using Crm.Domain.Forms;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Crm.Infrastructure.Persistence.Configurations;

internal sealed class FormDefinitionConfiguration : IEntityTypeConfiguration<FormDefinition>
{
    public void Configure(EntityTypeBuilder<FormDefinition> builder)
    {
        builder.Property(x => x.Code).HasMaxLength(40).IsRequired();
        builder.HasIndex(x => x.Code).IsUnique().HasFilter("[IsDeleted] = 0");

        // Localized texts and the complete field schema are stored in JSON columns.
        builder.ComplexProperty(x => x.Title, title => title.ToJson());
        builder.ComplexProperty(x => x.Description, description => description.ToJson());
        builder.ComplexCollection(x => x.Fields, fields =>
        {
            fields.ToJson();
            fields.ComplexProperty(f => f.Label);
            fields.ComplexCollection(f => f.Options, options => options.ComplexProperty(o => o.Label));
        });
    }
}

internal sealed class FormSubmissionConfiguration : IEntityTypeConfiguration<FormSubmission>
{
    public void Configure(EntityTypeBuilder<FormSubmission> builder)
    {
        builder.Property(x => x.Title).HasMaxLength(300).IsRequired();
        builder.Property(x => x.SubmittedByName).HasMaxLength(256);
        builder.HasIndex(x => new { x.FormDefinitionId, x.CreatedAt });
        builder.HasOne(x => x.FormDefinition).WithMany(f => f.Submissions).HasForeignKey(x => x.FormDefinitionId);

        // The answers of a submission live in a single JSON column.
        builder.ComplexCollection(x => x.Values, values => values.ToJson());
        builder.Ignore(x => x.EntityType);
        builder.Ignore(x => x.DisplayName);
    }
}
