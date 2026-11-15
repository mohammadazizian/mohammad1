using System.Linq.Expressions;
using Crm.Domain.Collaboration;
using Crm.Domain.Forms;
using Crm.Domain.Inventory;
using Crm.Domain.Sales;
using Crm.Infrastructure.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;

namespace Crm.Infrastructure.Persistence;

public class ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
    : IdentityDbContext<ApplicationUser, ApplicationRole, Guid>(options), IApplicationDbContext
{
    public DbSet<Customer> Customers => Set<Customer>();
    public DbSet<Contact> Contacts => Set<Contact>();
    public DbSet<Interaction> Interactions => Set<Interaction>();
    public DbSet<Lead> Leads => Set<Lead>();
    public DbSet<Pipeline> Pipelines => Set<Pipeline>();
    public DbSet<PipelineStage> PipelineStages => Set<PipelineStage>();
    public DbSet<Deal> Deals => Set<Deal>();

    public DbSet<Category> Categories => Set<Category>();
    public DbSet<Product> Products => Set<Product>();
    public DbSet<Warehouse> Warehouses => Set<Warehouse>();
    public DbSet<StockLevel> StockLevels => Set<StockLevel>();
    public DbSet<InventoryTransaction> InventoryTransactions => Set<InventoryTransaction>();

    public DbSet<ChatMessage> ChatMessages => Set<ChatMessage>();
    public DbSet<TaskItem> Tasks => Set<TaskItem>();
    public DbSet<Reminder> Reminders => Set<Reminder>();
    public DbSet<ActivityLog> ActivityLogs => Set<ActivityLog>();
    public DbSet<Notification> Notifications => Set<Notification>();

    public DbSet<FormDefinition> FormDefinitions => Set<FormDefinition>();
    public DbSet<FormSubmission> FormSubmissions => Set<FormSubmission>();

    protected override void ConfigureConventions(ModelConfigurationBuilder configurationBuilder)
    {
        configurationBuilder.Properties<decimal>().HavePrecision(18, 4);
    }

    protected override void OnModelCreating(ModelBuilder builder)
    {
        base.OnModelCreating(builder);
        builder.ApplyConfigurationsFromAssembly(typeof(ApplicationDbContext).Assembly);

        foreach (var entityType in builder.Model.GetEntityTypes().Where(t => typeof(BaseEntity).IsAssignableFrom(t.ClrType)))
        {
            // Ids are generated in the domain (Guid v7), never by the database.
            builder.Entity(entityType.ClrType).Property(nameof(BaseEntity.Id)).ValueGeneratedNever();
            builder.Entity(entityType.ClrType).Ignore(nameof(BaseEntity.DomainEvents));

            // Deletes are soft, so no relationship may cascade physically.
            foreach (var foreignKey in entityType.GetForeignKeys())
            {
                foreignKey.DeleteBehavior = DeleteBehavior.Restrict;
            }

            if (typeof(ISoftDelete).IsAssignableFrom(entityType.ClrType))
            {
                builder.Entity(entityType.ClrType).HasQueryFilter(SoftDeleteFilter(entityType.ClrType));
                builder.Entity(entityType.ClrType).HasIndex(nameof(ISoftDelete.IsDeleted));
            }
        }
    }

    /// <summary>Builds <c>e =&gt; !e.IsDeleted</c> for the given entity type.</summary>
    private static LambdaExpression SoftDeleteFilter(Type entityType)
    {
        var parameter = Expression.Parameter(entityType, "e");
        var isDeleted = Expression.Property(parameter, nameof(ISoftDelete.IsDeleted));
        return Expression.Lambda(Expression.Not(isDeleted), parameter);
    }
}
