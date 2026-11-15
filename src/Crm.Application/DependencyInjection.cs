using System.Reflection;
using Crm.Application.Common.Behaviors;
using Crm.Application.Common.Services;
using Microsoft.Extensions.DependencyInjection;

namespace Crm.Application;

public static class DependencyInjection
{
    public static IServiceCollection AddApplication(this IServiceCollection services)
    {
        var assembly = Assembly.GetExecutingAssembly();

        services.AddValidatorsFromAssembly(assembly, includeInternalTypes: true);
        services.AddMediatR(configuration =>
        {
            configuration.RegisterServicesFromAssembly(assembly);
            configuration.AddOpenBehavior(typeof(LoggingBehavior<,>));
            configuration.AddOpenBehavior(typeof(ValidationBehavior<,>));
        });

        services.AddScoped<ITrackableEntityResolver, TrackableEntityResolver>();
        services.AddScoped<INotificationService, NotificationService>();
        services.TryAddSingletonTimeProvider();
        return services;
    }

    private static void TryAddSingletonTimeProvider(this IServiceCollection services)
    {
        if (services.All(d => d.ServiceType != typeof(TimeProvider)))
        {
            services.AddSingleton(TimeProvider.System);
        }
    }
}
