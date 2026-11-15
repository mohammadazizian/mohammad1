using System.Diagnostics;
using Microsoft.Extensions.Logging;

namespace Crm.Application.Common.Behaviors;

/// <summary>Runs every FluentValidation validator registered for the request before its handler.</summary>
public sealed class ValidationBehavior<TRequest, TResponse>(IEnumerable<IValidator<TRequest>> validators)
    : IPipelineBehavior<TRequest, TResponse>
    where TRequest : notnull
{
    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        if (validators.Any())
        {
            var context = new ValidationContext<TRequest>(request);
            var results = await Task.WhenAll(validators.Select(v => v.ValidateAsync(context, cancellationToken)));
            var failures = results.SelectMany(r => r.Errors).Where(f => f is not null).ToList();
            if (failures.Count != 0)
            {
                throw new AppValidationException(failures);
            }
        }

        return await next(cancellationToken);
    }
}

/// <summary>Structured logging of failed and slow requests.</summary>
public sealed class LoggingBehavior<TRequest, TResponse>(
    ILogger<LoggingBehavior<TRequest, TResponse>> logger,
    ICurrentUser currentUser)
    : IPipelineBehavior<TRequest, TResponse>
    where TRequest : notnull
{
    private const int SlowRequestMilliseconds = 500;

    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        var requestName = typeof(TRequest).Name;
        var stopwatch = Stopwatch.StartNew();
        try
        {
            var response = await next(cancellationToken);
            stopwatch.Stop();
            if (stopwatch.ElapsedMilliseconds > SlowRequestMilliseconds)
            {
                logger.LogWarning(
                    "Slow request {RequestName} took {ElapsedMs} ms (user {UserName})",
                    requestName, stopwatch.ElapsedMilliseconds, currentUser.UserName);
            }

            return response;
        }
        catch (Exception ex) when (ex is not (AppValidationException or NotFoundException or DomainException or ForbiddenAccessException))
        {
            logger.LogError(ex, "Request {RequestName} failed for user {UserName}", requestName, currentUser.UserName);
            throw;
        }
    }
}

/// <summary>Adapter that lets MediatR publish framework-free domain events.</summary>
public sealed record DomainEventNotification<TEvent>(TEvent Event) : INotification
    where TEvent : IDomainEvent;
