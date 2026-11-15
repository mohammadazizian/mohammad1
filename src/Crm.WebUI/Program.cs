using Crm.Application;
using Crm.Application.Common.Exceptions;
using Crm.Application.Common.Interfaces;
using Crm.Domain.Common;
using Crm.Infrastructure;
using Crm.Infrastructure.Persistence;
using Crm.Infrastructure.Realtime;
using Crm.WebUI.Services;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Serilog;

Log.Logger = new LoggerConfiguration().WriteTo.Console().CreateBootstrapLogger();

try
{
    var builder = WebApplication.CreateBuilder(args);

    // Structured logging (sinks and levels come from the "Serilog" configuration section).
    builder.Host.UseSerilog((context, services, configuration) => configuration
        .ReadFrom.Configuration(context.Configuration)
        .ReadFrom.Services(services)
        .Enrich.FromLogContext());

    // ---- Composition root: one registration call per layer -------------------------------
    builder.Services.AddApplication();
    builder.Services.AddInfrastructure(builder.Configuration);
    builder.Services.AddWebUi(builder.Configuration);

    var app = builder.Build();
    app.UseLocalizedValidation();

    // ---- HTTP pipeline -------------------------------------------------------------------
    app.UseExceptionHandler(new ExceptionHandlerOptions
    {
        ExceptionHandlingPath = "/Error",
        StatusCodeSelector = GlobalExceptionHandler.StatusCodeFor,
        SuppressDiagnosticsCallback = context => GlobalExceptionHandler.StatusCodeFor(context.Exception) < 500,
    });
    app.UseStatusCodePagesWithReExecute("/Error", "?code={0}");

    if (!app.Environment.IsDevelopment())
    {
        app.UseForwardedHeaders();
    }

    app.UseStaticFiles();
    app.UseSerilogRequestLogging(options =>
        options.GetLevel = (context, _, exception) =>
            exception is not null || context.Response.StatusCode >= 500
                ? Serilog.Events.LogEventLevel.Error
                : context.Request.Path.StartsWithSegments("/health")
                    ? Serilog.Events.LogEventLevel.Verbose
                    : Serilog.Events.LogEventLevel.Information);

    app.UseRouting();
    app.UseRequestLocalization();
    app.UseAuthentication();
    app.UseAuthorization();

    app.MapRazorPages();
    app.MapHub<ChatHub>(ChatHub.Route);
    app.MapHub<NotificationHub>(NotificationHub.Route);
    app.MapHealthChecks("/health", new HealthCheckOptions()).AllowAnonymous();

    // ---- Automated startup: migrations + seed data ---------------------------------------
    await using (var scope = app.Services.CreateAsyncScope())
    {
        await scope.ServiceProvider.GetRequiredService<DataSeeder>().InitializeAsync();
    }

    await app.RunAsync();
}
catch (Exception ex) when (ex is not HostAbortedException)
{
    Log.Fatal(ex, "Application terminated unexpectedly");
    Environment.ExitCode = 1;
}
finally
{
    await Log.CloseAndFlushAsync();
}

/// <summary>Entry point marker (also lets integration tests reference the web application).</summary>
public partial class Program;
