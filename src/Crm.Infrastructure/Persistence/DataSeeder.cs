using System.Security.Claims;
using Crm.Application.Common.Security;
using Crm.Domain.Collaboration;
using Crm.Domain.Forms;
using Crm.Domain.Inventory;
using Crm.Domain.Sales;
using Crm.Infrastructure.Identity;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Crm.Infrastructure.Persistence;

public sealed class SeedOptions
{
    public const string SectionName = "Seed";

    public bool ApplyMigrations { get; set; } = true;
    public bool DemoData { get; set; } = true;
    public string AdminUserName { get; set; } = "admin";
    public string AdminPassword { get; set; } = "Admin@12345";
    public string AdminEmail { get; set; } = "admin@crm.local";
    public string DemoPassword { get; set; } = "Demo@12345";
}

/// <summary>
/// Applies pending migrations and seeds the data that makes the application usable right after
/// the first start: roles with permissions, the admin user and (optionally) bilingual demo data.
/// Every step is idempotent.
/// </summary>
public sealed class DataSeeder(
    ApplicationDbContext db,
    UserManager<ApplicationUser> userManager,
    RoleManager<ApplicationRole> roleManager,
    IOptions<SeedOptions> options,
    TimeProvider clock,
    ILogger<DataSeeder> logger)
{
    private const string SalesManagerRole = "Sales Manager";
    private const string SalesRepRole = "Sales Representative";
    private const string WarehouseRole = "Warehouse Keeper";

    private readonly SeedOptions _options = options.Value;

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        if (_options.ApplyMigrations)
        {
            await MigrateWithRetryAsync(cancellationToken);
        }

        await SeedRolesAsync();
        var admin = await SeedUserAsync(_options.AdminUserName, "System Administrator", _options.AdminEmail, _options.AdminPassword, Permissions.AdministratorRole);
        await SeedPipelineAsync(cancellationToken);

        if (_options.DemoData && !await db.Customers.IgnoreQueryFilters().AnyAsync(cancellationToken))
        {
            await SeedDemoDataAsync(admin, cancellationToken);
            logger.LogInformation("Demo data seeded");
        }
    }

    /// <summary>The database container may still be starting, so keep trying for a while.</summary>
    private async Task MigrateWithRetryAsync(CancellationToken cancellationToken)
    {
        const int maxAttempts = 30;
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                await db.Database.MigrateAsync(cancellationToken);
                logger.LogInformation("Database is up to date");
                return;
            }
            catch (Exception ex) when (attempt < maxAttempts && ex is not OperationCanceledException)
            {
                logger.LogWarning("Database not ready (attempt {Attempt}/{Max}): {Message}", attempt, maxAttempts, ex.Message);
                await Task.Delay(TimeSpan.FromSeconds(3), cancellationToken);
            }
        }
    }

    private async Task SeedRolesAsync()
    {
        string[] crud = [.. Permissions.Actions.All];
        string[] read = [Permissions.Actions.View];
        string[] readWrite = [Permissions.Actions.View, Permissions.Actions.Create, Permissions.Actions.Edit];

        await SeedRoleAsync(Permissions.AdministratorRole, "Full access to everything", isSystem: true, []);

        await SeedRoleAsync(SalesManagerRole, "Manages the sales team and pipeline", isSystem: false,
        [
            .. Grant(Permissions.Modules.Dashboard, read),
            .. Grant(Permissions.Modules.Customers, crud),
            .. Grant(Permissions.Modules.Leads, crud),
            .. Grant(Permissions.Modules.Deals, crud),
            .. Grant(Permissions.Modules.Products, read),
            .. Grant(Permissions.Modules.Inventory, read),
            .. Grant(Permissions.Modules.Tasks, crud),
            .. Grant(Permissions.Modules.Chat, readWrite),
            .. Grant(Permissions.Modules.Reports, readWrite),
            .. Grant(Permissions.FormModule(DemoFormCode), crud),
        ]);

        await SeedRoleAsync(SalesRepRole, "Works leads, customers and deals", isSystem: false,
        [
            .. Grant(Permissions.Modules.Dashboard, read),
            .. Grant(Permissions.Modules.Customers, readWrite),
            .. Grant(Permissions.Modules.Leads, readWrite),
            .. Grant(Permissions.Modules.Deals, readWrite),
            .. Grant(Permissions.Modules.Products, read),
            .. Grant(Permissions.Modules.Tasks, readWrite),
            .. Grant(Permissions.Modules.Chat, readWrite),
            .. Grant(Permissions.FormModule(DemoFormCode), [Permissions.Actions.View, Permissions.Actions.Create]),
        ]);

        await SeedRoleAsync(WarehouseRole, "Maintains products and stock", isSystem: false,
        [
            .. Grant(Permissions.Modules.Dashboard, read),
            .. Grant(Permissions.Modules.Products, readWrite),
            .. Grant(Permissions.Modules.Inventory, crud),
            .. Grant(Permissions.Modules.Tasks, readWrite),
            .. Grant(Permissions.Modules.Chat, readWrite),
        ]);
    }

    private static IEnumerable<string> Grant(string module, IEnumerable<string> actions) =>
        actions.Select(action => Permissions.For(module, action));

    private async Task SeedRoleAsync(string name, string description, bool isSystem, IReadOnlyCollection<string> permissions)
    {
        if (await roleManager.RoleExistsAsync(name))
        {
            return;
        }

        var role = new ApplicationRole(name, description, isSystem) { Id = Guid.CreateVersion7() };
        Ensure(await roleManager.CreateAsync(role));
        foreach (var permission in permissions)
        {
            Ensure(await roleManager.AddClaimAsync(role, new Claim(Permissions.ClaimType, permission)));
        }
    }

    private async Task<ApplicationUser> SeedUserAsync(string userName, string fullName, string email, string password, string role)
    {
        var user = await userManager.FindByNameAsync(userName);
        if (user is not null)
        {
            return user;
        }

        user = new ApplicationUser
        {
            Id = Guid.CreateVersion7(),
            UserName = userName,
            FullName = fullName,
            Email = email,
            EmailConfirmed = true,
        };
        Ensure(await userManager.CreateAsync(user, password));
        Ensure(await userManager.AddToRoleAsync(user, role));
        logger.LogInformation("Seeded user {UserName} ({Role})", userName, role);
        return user;
    }

    private static void Ensure(IdentityResult result)
    {
        if (!result.Succeeded)
        {
            throw new InvalidOperationException("Seeding identity data failed: " + string.Join("; ", result.Errors.Select(e => e.Description)));
        }
    }

    private async Task SeedPipelineAsync(CancellationToken cancellationToken)
    {
        if (await db.Pipelines.IgnoreQueryFilters().AnyAsync(cancellationToken))
        {
            return;
        }

        var pipeline = new Pipeline { Name = "Sales Pipeline", IsDefault = true };
        (string En, string Fa, int Probability, bool Won, bool Lost)[] stages =
        [
            ("Qualification", "ارزیابی اولیه", 10, false, false),
            ("Needs Analysis", "نیازسنجی", 30, false, false),
            ("Proposal", "ارائه پیشنهاد", 55, false, false),
            ("Negotiation", "مذاکره", 80, false, false),
            ("Won", "موفق", 100, true, false),
            ("Lost", "ناموفق", 0, false, true),
        ];

        for (var i = 0; i < stages.Length; i++)
        {
            pipeline.Stages.Add(new PipelineStage
            {
                Name = new LocalizedText(stages[i].En, stages[i].Fa),
                Order = i,
                Probability = stages[i].Probability,
                IsWon = stages[i].Won,
                IsLost = stages[i].Lost,
            });
        }

        db.Pipelines.Add(pipeline);
        await db.SaveChangesAsync(cancellationToken);
    }

    public const string DemoFormCode = "site-visit";

    private async Task SeedDemoDataAsync(ApplicationUser admin, CancellationToken cancellationToken)
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var sara = await SeedUserAsync("sara", "Sara Ahmadi", "sara@crm.local", _options.DemoPassword, SalesManagerRole);
        var reza = await SeedUserAsync("reza", "Reza Karimi", "reza@crm.local", _options.DemoPassword, WarehouseRole);
        await SeedUserAsync("mina", "Mina Rahimi", "mina@crm.local", _options.DemoPassword, SalesRepRole);

        // ---- Catalogue & inventory -------------------------------------------------------------
        var electronics = new Category { Name = new LocalizedText("Electronics", "الکترونیک") };
        var office = new Category { Name = new LocalizedText("Office Supplies", "لوازم اداری") };
        var networking = new Category { Name = new LocalizedText("Networking", "تجهیزات شبکه") };
        db.Categories.AddRange(electronics, office, networking);

        var mainWarehouse = new Warehouse { Code = "THR-01", Name = "Tehran Central Warehouse", Location = "Tehran" };
        var secondWarehouse = new Warehouse { Code = "ISF-01", Name = "Isfahan Depot", Location = "Isfahan" };
        db.Warehouses.AddRange(mainWarehouse, secondWarehouse);

        var products = new[]
        {
            NewProduct("LAP-PRO-14", "ProBook 14\" Laptop", electronics, 1250m, 980m, 5, "pcs"),
            NewProduct("MON-27-4K", "27\" 4K Monitor", electronics, 420m, 310m, 8, "pcs"),
            NewProduct("KBD-MECH-01", "Mechanical Keyboard", electronics, 85m, 52m, 15, "pcs"),
            NewProduct("RTR-AX-3000", "Wi-Fi 6 Router AX3000", networking, 140m, 96m, 10, "pcs"),
            NewProduct("SWT-24-POE", "24-Port PoE Switch", networking, 380m, 275m, 4, "pcs"),
            NewProduct("CHR-ERGO-01", "Ergonomic Office Chair", office, 230m, 150m, 6, "pcs"),
            NewProduct("PPR-A4-80", "A4 Paper 80g (box)", office, 28m, 19m, 40, "box"),
        };
        db.Products.AddRange(products);

        (int Product, Warehouse Warehouse, decimal Quantity)[] openingStock =
        [
            (0, mainWarehouse, 12), (0, secondWarehouse, 4), (1, mainWarehouse, 20), (2, mainWarehouse, 60),
            (2, secondWarehouse, 25), (3, mainWarehouse, 9), (4, mainWarehouse, 3), (5, mainWarehouse, 14),
            (5, secondWarehouse, 6), (6, mainWarehouse, 35),
        ];

        var transactions = new List<InventoryTransaction>();
        foreach (var (index, warehouse, quantity) in openingStock)
        {
            var level = new StockLevel { ProductId = products[index].Id, WarehouseId = warehouse.Id };
            level.Increase(quantity, now);
            db.StockLevels.Add(level);
            transactions.Add(InventoryTransaction.Create(
                StockMovementType.In, products[index].Id, null, warehouse.Id, quantity, "OPENING", "Opening balance", now.AddDays(-20)));
        }

        db.InventoryTransactions.AddRange(transactions);

        // ---- CRM -------------------------------------------------------------------------------
        var customers = new[]
        {
            NewCustomer("Pars Tech Solutions", CustomerType.B2B, "info@parstech.example", "+98 21 5550 1001", "Tehran", "Iran", ("Ali", "Mohammadi", "CTO")),
            NewCustomer("Aria Trading Co.", CustomerType.B2B, "sales@ariatrading.example", "+98 31 5550 2002", "Isfahan", "Iran", ("Maryam", "Hosseini", "Procurement Manager")),
            NewCustomer("Northwind Traders", CustomerType.B2B, "contact@northwind.example", "+1 206 555 0100", "Seattle", "USA", ("Nancy", "Davolio", "Purchasing Lead")),
            NewCustomer("Kian Rostami", CustomerType.B2C, "kian.rostami@example.com", "+98 912 555 3003", "Shiraz", "Iran", null),
            NewCustomer("Contoso Retail", CustomerType.B2B, "hello@contoso.example", "+44 20 5550 4004", "London", "UK", ("James", "Carter", "IT Director")),
        };
        db.Customers.AddRange(customers);

        customers[0].Interactions.Add(new Interaction
        {
            Type = InteractionType.Meeting, Subject = "Kick-off meeting", Notes = "Discussed the laptop refresh project for 40 seats.",
            OccurredAt = now.AddDays(-6), UserName = sara.FullName,
        });
        customers[0].Interactions.Add(new Interaction
        {
            Type = InteractionType.Call, Subject = "Follow-up call", Notes = "Asked for a revised quote including monitors.",
            OccurredAt = now.AddDays(-2), UserName = sara.FullName,
        });

        db.Leads.AddRange(
            new Lead { Name = "Neda Sharifi", Company = "Sepehr Logistics", Email = "n.sharifi@sepehr.example", Phone = "+98 21 5550 7001", Source = LeadSource.Website, Status = LeadStatus.New, EstimatedValue = 18000 },
            new Lead { Name = "Omid Farahani", Company = "Farahani Architects", Email = "omid@farahani.example", Source = LeadSource.Referral, Status = LeadStatus.Contacted, EstimatedValue = 7500 },
            new Lead { Name = "Laura Smith", Company = "Bluewave Media", Email = "laura@bluewave.example", Source = LeadSource.Exhibition, Status = LeadStatus.Qualified, EstimatedValue = 32000 },
            new Lead { Name = "Hamid Jalali", Email = "hamid.jalali@example.com", Source = LeadSource.Campaign, Status = LeadStatus.New, EstimatedValue = 1200 });

        var pipeline = await db.Pipelines.Include(p => p.Stages).FirstAsync(p => p.IsDefault, cancellationToken);
        var stages = pipeline.Stages.OrderBy(s => s.Order).ToList();
        var deals = new[]
        {
            NewDeal("Laptop refresh - 40 seats", customers[0], stages[2], 50000m, now.AddDays(21)),
            NewDeal("Network upgrade", customers[0], stages[1], 14500m, now.AddDays(35)),
            NewDeal("Office furniture package", customers[1], stages[3], 9200m, now.AddDays(10)),
            NewDeal("Annual paper supply", customers[1], stages[4], 3360m, now.AddDays(-3)),
            NewDeal("Monitor bundle", customers[2], stages[0], 8400m, now.AddDays(45)),
            NewDeal("Store Wi-Fi rollout", customers[4], stages[2], 22400m, now.AddDays(28)),
            NewDeal("Home office setup", customers[3], stages[5], 1900m, now.AddDays(-8)),
        };
        db.Deals.AddRange(deals);

        // ---- Dynamic form (bilingual) + a submission ---------------------------------------------
        var form = new FormDefinition
        {
            Title = new LocalizedText("Customer Site Visit Report", "گزارش بازدید از مشتری"),
            Description = new LocalizedText("Filled in by the sales team after every customer visit.", "پس از هر بازدید از مشتری توسط تیم فروش تکمیل می‌شود."),
        };
        form.SetCode(DemoFormCode);
        form.SetFields(
        [
            new FormField { Key = "customer", Type = FormFieldType.EntityLookup, LookupEntityType = TrackableEntityType.Customer, Required = true, Label = new LocalizedText("Customer", "مشتری") },
            new FormField { Key = "visitDate", Type = FormFieldType.Date, Required = true, Label = new LocalizedText("Visit date", "تاریخ بازدید") },
            new FormField
            {
                Key = "visitType", Type = FormFieldType.Dropdown, Required = true, Label = new LocalizedText("Visit type", "نوع بازدید"),
                Options =
                [
                    new FormFieldOption { Value = "onsite", Label = new LocalizedText("On-site", "حضوری") },
                    new FormFieldOption { Value = "online", Label = new LocalizedText("Online meeting", "جلسه آنلاین") },
                    new FormFieldOption { Value = "phone", Label = new LocalizedText("Phone call", "تماس تلفنی") },
                ],
            },
            new FormField { Key = "attendees", Type = FormFieldType.Number, Min = 1, Max = 50, Label = new LocalizedText("Number of attendees", "تعداد حاضران") },
            new FormField { Key = "product", Type = FormFieldType.EntityLookup, LookupEntityType = TrackableEntityType.Product, Label = new LocalizedText("Product of interest", "محصول مورد علاقه") },
            new FormField { Key = "contactPhone", Type = FormFieldType.Text, MaxLength = 20, Pattern = @"^\+?[0-9 ]{7,20}$", Label = new LocalizedText("Contact phone", "تلفن تماس") },
            new FormField { Key = "summary", Type = FormFieldType.TextArea, Required = true, MaxLength = 2000, Label = new LocalizedText("Summary & next steps", "خلاصه و اقدامات بعدی") },
            new FormField { Key = "attachment", Type = FormFieldType.File, Label = new LocalizedText("Attachment", "پیوست") },
        ]);
        db.FormDefinitions.Add(form);

        var submission = new FormSubmission
        {
            FormDefinitionId = form.Id,
            Title = $"{form.Title.En} #1",
            SubmittedByName = sara.FullName,
            Values =
            [
                new FormFieldValue { Key = "customer", Value = customers[0].Id.ToString(), Display = customers[0].Name },
                new FormFieldValue { Key = "visitDate", Value = now.AddDays(-6).ToString("yyyy-MM-dd") },
                new FormFieldValue { Key = "visitType", Value = "onsite" },
                new FormFieldValue { Key = "attendees", Value = "4" },
                new FormFieldValue { Key = "product", Value = products[0].Id.ToString(), Display = products[0].DisplayName },
                new FormFieldValue { Key = "contactPhone", Value = "+98 21 5550 1001" },
                new FormFieldValue { Key = "summary", Value = "Customer wants a pilot of 5 laptops before the full order. Send revised quote this week." },
                new FormFieldValue { Key = "attachment" },
            ],
        };
        db.FormSubmissions.Add(submission);

        // ---- Collaboration on top of the polymorphic engine ---------------------------------------
        var followUp = new TaskItem
        {
            Title = "Send revised quote including monitors", Priority = TaskPriority.High, DueAt = now.AddDays(2),
            AssignedToUserId = sara.Id, AssignedToUserName = sara.FullName,
        };
        followUp.BindTo(EntityRef.Of(customers[0]), customers[0].DisplayName);
        followUp.Reminders.Add(new Reminder
        {
            UserId = sara.Id, Message = followUp.Title, RemindAt = now.AddDays(1),
            EntityType = TrackableEntityType.Customer, EntityId = customers[0].Id,
        });

        var restock = new TaskItem
        {
            Title = "Reorder 24-Port PoE switches", Priority = TaskPriority.Urgent, DueAt = now.AddDays(1), AssignedToRole = WarehouseRole,
        };
        restock.BindTo(EntityRef.Of(products[4]), products[4].DisplayName);

        var pilot = new TaskItem
        {
            Title = "Prepare 5-laptop pilot delivery", Priority = TaskPriority.Normal, DueAt = now.AddDays(5),
            AssignedToUserId = reza.Id, AssignedToUserName = reza.FullName,
        };
        pilot.BindTo(EntityRef.Of(submission), submission.DisplayName);

        var review = new TaskItem
        {
            Title = "Review Q4 sales targets", Priority = TaskPriority.Low, DueAt = now.AddDays(-1),
            AssignedToUserId = admin.Id, AssignedToUserName = admin.FullName,
        };
        db.Tasks.AddRange(followUp, restock, pilot, review);

        var question = new ChatMessage
        {
            EntityType = TrackableEntityType.Customer, EntityId = customers[0].Id, AuthorId = sara.Id, AuthorName = sara.FullName,
            Body = $"@admin the customer asked for a pilot first. Can we reserve stock of #[Product:{products[0].Id}|{products[0].Name}]?",
            MentionedUserIds = [admin.Id],
        };
        db.ChatMessages.AddRange(
            question,
            new ChatMessage
            {
                EntityType = TrackableEntityType.Customer, EntityId = customers[0].Id, AuthorId = admin.Id, AuthorName = admin.FullName,
                Body = "Yes - @reza please keep 5 units aside in Tehran.", ParentMessageId = question.Id, MentionedUserIds = [reza.Id],
            },
            new ChatMessage
            {
                EntityType = TrackableEntityType.FormSubmission, EntityId = submission.Id, AuthorId = sara.Id, AuthorName = sara.FullName,
                Body = "گزارش بازدید ثبت شد. @reza لطفاً موجودی لپ‌تاپ را بررسی کن.", MentionedUserIds = [reza.Id],
            });

        await db.SaveChangesAsync(cancellationToken);
    }

    private static Product NewProduct(string sku, string name, Category category, decimal price, decimal cost, decimal threshold, string unit)
    {
        var product = new Product { Name = name, Category = category, UnitPrice = price, Cost = cost, LowStockThreshold = threshold, Unit = unit };
        product.SetSku(sku);
        return product;
    }

    private static Customer NewCustomer(
        string name, CustomerType type, string email, string phone, string city, string country,
        (string First, string Last, string Position)? contact)
    {
        var customer = new Customer
        {
            Name = name, Type = type, Email = email, Phone = phone,
            Address = new Address { City = city, Country = country },
        };

        if (contact is { } c)
        {
            customer.Contacts.Add(new Contact { FirstName = c.First, LastName = c.Last, Position = c.Position, Email = email, IsPrimary = true });
        }

        return customer;
    }

    private Deal NewDeal(string title, Customer customer, PipelineStage stage, decimal amount, DateTime expectedClose)
    {
        var deal = new Deal { Title = title, Customer = customer, PipelineId = stage.PipelineId, Amount = amount, ExpectedCloseDate = expectedClose };
        deal.MoveTo(stage, clock.GetUtcNow().UtcDateTime);
        return deal;
    }
}
