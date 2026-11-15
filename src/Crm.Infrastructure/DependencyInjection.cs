using Crm.Application.Common.Specifications;
using Crm.Application.Features.Reports;
using Crm.Infrastructure.BackgroundJobs;
using Crm.Infrastructure.Files;
using Crm.Infrastructure.Identity;
using Crm.Infrastructure.Localization;
using Crm.Infrastructure.Persistence;
using Crm.Infrastructure.Persistence.Interceptors;
using Crm.Infrastructure.Realtime;
using Crm.Infrastructure.Reports;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Crm.Infrastructure;

public static class DependencyInjection
{
    public const string ConnectionStringName = "DefaultConnection";

    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        var connectionString = configuration.GetConnectionString(ConnectionStringName)
            ?? throw new InvalidOperationException($"Connection string '{ConnectionStringName}' is not configured.");

        // --- Persistence ---------------------------------------------------------------------
        services.AddScoped<ISaveChangesInterceptor, AuditableEntityInterceptor>();
        services.AddScoped<ISaveChangesInterceptor, DispatchDomainEventsInterceptor>();

        services.AddDbContext<ApplicationDbContext>((provider, options) =>
        {
            options.AddInterceptors(provider.GetServices<ISaveChangesInterceptor>());
            options.UseSqlServer(connectionString, sql =>
            {
                sql.MigrationsAssembly(typeof(ApplicationDbContext).Assembly.FullName);
                sql.UseQuerySplittingBehavior(QuerySplittingBehavior.SplitQuery);
            });

            // Soft-deleted principals are intentionally hidden from their dependents.
            options.ConfigureWarnings(w => w.Ignore(CoreEventId.PossibleIncorrectRequiredNavigationWithQueryFilterInteractionWarning));
        });

        services.AddScoped<IApplicationDbContext>(provider => provider.GetRequiredService<ApplicationDbContext>());
        services.AddScoped(typeof(IReadRepository<>), typeof(EfReadRepository<>));
        services.AddScoped<DataSeeder>();
        services.Configure<SeedOptions>(configuration.GetSection(SeedOptions.SectionName));

        // --- Identity & access management ----------------------------------------------------
        services
            .AddIdentity<ApplicationUser, ApplicationRole>(options =>
            {
                options.Password.RequiredLength = 8;
                options.Password.RequireNonAlphanumeric = false;
                options.User.RequireUniqueEmail = false;
                options.Lockout.MaxFailedAccessAttempts = 5;
                options.Lockout.DefaultLockoutTimeSpan = TimeSpan.FromMinutes(10);
            })
            .AddEntityFrameworkStores<ApplicationDbContext>()
            .AddClaimsPrincipalFactory<AppClaimsPrincipalFactory>()
            .AddDefaultTokenProviders();

        // Re-validate the cookie regularly so role / activation changes reach signed-in users.
        services.Configure<SecurityStampValidatorOptions>(options => options.ValidationInterval = TimeSpan.FromMinutes(1));

        services.AddMemoryCache();
        services.AddScoped<IPermissionService, PermissionService>();
        services.AddScoped<IIdentityService, IdentityService>();
        services.AddScoped<ISignInService, SignInService>();
        services.AddSingleton<IAuthorizationPolicyProvider, PermissionPolicyProvider>();
        services.AddScoped<IAuthorizationHandler, PermissionAuthorizationHandler>();

        // --- Real-time, background jobs, files, localization, reports -------------------------
        services.AddSignalR();
        services.AddSingleton<IRealtimeNotifier, SignalRRealtimeNotifier>();

        services.Configure<ReminderOptions>(configuration.GetSection(ReminderOptions.SectionName));
        services.AddHostedService<ReminderWorker>();

        services.Configure<FileStorageOptions>(configuration.GetSection(FileStorageOptions.SectionName));
        services.AddSingleton<IFileStorage, LocalFileStorage>();

        services.Configure<RegionalOptions>(configuration.GetSection(RegionalOptions.SectionName));
        services.AddSingleton<ICultureContext, CultureContext>();
        services.AddSingleton<ILocalizedFormatter, LocalizedFormatter>();

        services.AddSingleton<IReportExporter, ReportExporter>();

        services.AddHealthChecks().AddDbContextCheck<ApplicationDbContext>("database");
        return services;
    }
}
