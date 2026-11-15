using Crm.Domain.Collaboration;
using Crm.Domain.Forms;
using Crm.Domain.Inventory;
using Crm.Domain.Sales;

namespace Crm.Application.Common.Interfaces;

/// <summary>Persistence port used by the CQRS handlers.</summary>
public interface IApplicationDbContext
{
    DbSet<Customer> Customers { get; }
    DbSet<Contact> Contacts { get; }
    DbSet<Interaction> Interactions { get; }
    DbSet<Lead> Leads { get; }
    DbSet<Pipeline> Pipelines { get; }
    DbSet<PipelineStage> PipelineStages { get; }
    DbSet<Deal> Deals { get; }

    DbSet<Category> Categories { get; }
    DbSet<Product> Products { get; }
    DbSet<Warehouse> Warehouses { get; }
    DbSet<StockLevel> StockLevels { get; }
    DbSet<InventoryTransaction> InventoryTransactions { get; }

    DbSet<ChatMessage> ChatMessages { get; }
    DbSet<TaskItem> Tasks { get; }
    DbSet<Reminder> Reminders { get; }
    DbSet<ActivityLog> ActivityLogs { get; }
    DbSet<Notification> Notifications { get; }

    DbSet<FormDefinition> FormDefinitions { get; }
    DbSet<FormSubmission> FormSubmissions { get; }

    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
