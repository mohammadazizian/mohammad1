using Crm.Application.Features.Collaboration;
using MediatR;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Crm.Infrastructure.BackgroundJobs;

public sealed class ReminderOptions
{
    public const string SectionName = "Reminders";

    /// <summary>How often due reminders are looked up.</summary>
    public int PollSeconds { get; set; } = 30;
}

/// <summary>
/// Hosted background service: periodically delivers due reminders as in-app notifications,
/// which are pushed to the user's browser through SignalR.
/// </summary>
public sealed class ReminderWorker(
    IServiceScopeFactory scopeFactory,
    IOptions<ReminderOptions> options,
    ILogger<ReminderWorker> logger)
    : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = TimeSpan.FromSeconds(Math.Max(5, options.Value.PollSeconds));
        logger.LogInformation("Reminder worker started (every {Interval})", interval);

        using var timer = new PeriodicTimer(interval);
        try
        {
            do
            {
                await ProcessAsync(stoppingToken);
            }
            while (await timer.WaitForNextTickAsync(stoppingToken));
        }
        catch (OperationCanceledException)
        {
            // Application is shutting down.
        }
    }

    private async Task ProcessAsync(CancellationToken stoppingToken)
    {
        try
        {
            await using var scope = scopeFactory.CreateAsyncScope();
            var sender = scope.ServiceProvider.GetRequiredService<ISender>();
            var delivered = await sender.Send(new ProcessDueRemindersCommand(), stoppingToken);
            if (delivered > 0)
            {
                logger.LogInformation("Delivered {Count} reminder(s)", delivered);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger.LogError(ex, "Processing reminders failed; will retry on the next tick");
        }
    }
}
