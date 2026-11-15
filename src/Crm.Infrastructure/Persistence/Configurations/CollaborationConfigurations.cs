using Crm.Domain.Collaboration;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Crm.Infrastructure.Persistence.Configurations;

// Polymorphic associations: none of these tables has a foreign key to a concrete business
// table. They point at any ITrackableEntity through the indexed (EntityType, EntityId) pair.

internal sealed class ChatMessageConfiguration : IEntityTypeConfiguration<ChatMessage>
{
    public void Configure(EntityTypeBuilder<ChatMessage> builder)
    {
        builder.Property(x => x.Body).HasMaxLength(4000).IsRequired();
        builder.Property(x => x.AuthorName).HasMaxLength(256).IsRequired();
        builder.HasIndex(x => new { x.EntityType, x.EntityId, x.CreatedAt });
        builder.HasOne(x => x.ParentMessage).WithMany(m => m.Replies).HasForeignKey(x => x.ParentMessageId);

        // EF Core 10 JSON columns: attachments as a JSON document, mentions as a JSON array.
        builder.ComplexCollection(x => x.Attachments, attachments => attachments.ToJson());
        builder.PrimitiveCollection(x => x.MentionedUserIds);
        builder.Ignore(x => x.Entity);
    }
}

internal sealed class TaskItemConfiguration : IEntityTypeConfiguration<TaskItem>
{
    public void Configure(EntityTypeBuilder<TaskItem> builder)
    {
        builder.ToTable("Tasks");
        builder.Property(x => x.Title).HasMaxLength(200).IsRequired();
        builder.Property(x => x.Description).HasMaxLength(4000);
        builder.Property(x => x.AssignedToUserName).HasMaxLength(256);
        builder.Property(x => x.AssignedToRole).HasMaxLength(256);
        builder.Property(x => x.EntityDisplayName).HasMaxLength(300);
        builder.HasIndex(x => new { x.EntityType, x.EntityId });
        builder.HasIndex(x => new { x.AssignedToUserId, x.Status });
        builder.Ignore(x => x.IsOpen);
    }
}

internal sealed class ReminderConfiguration : IEntityTypeConfiguration<Reminder>
{
    public void Configure(EntityTypeBuilder<Reminder> builder)
    {
        builder.Property(x => x.Message).HasMaxLength(500).IsRequired();
        builder.HasIndex(x => new { x.SentAt, x.RemindAt });
        builder.HasIndex(x => new { x.EntityType, x.EntityId });
        builder.HasOne(x => x.TaskItem).WithMany(t => t.Reminders).HasForeignKey(x => x.TaskItemId);
        builder.Ignore(x => x.IsSent);
    }
}

internal sealed class ActivityLogConfiguration : IEntityTypeConfiguration<ActivityLog>
{
    public void Configure(EntityTypeBuilder<ActivityLog> builder)
    {
        builder.Property(x => x.EntityDisplayName).HasMaxLength(300).IsRequired();
        builder.Property(x => x.Details).HasMaxLength(1000);
        builder.Property(x => x.UserName).HasMaxLength(256);
        builder.HasIndex(x => new { x.EntityType, x.EntityId, x.OccurredAt });
        builder.HasIndex(x => x.OccurredAt);
    }
}

internal sealed class NotificationConfiguration : IEntityTypeConfiguration<Notification>
{
    public void Configure(EntityTypeBuilder<Notification> builder)
    {
        builder.Property(x => x.Message).HasMaxLength(500).IsRequired();
        builder.HasIndex(x => new { x.UserId, x.IsRead, x.CreatedAt });
    }
}
