using Crm.Application.Common.Exceptions;
using Crm.Application.Features.Forms;
using Crm.Domain.Common;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Localization;

namespace Crm.WebUI.Support;

/// <summary>
/// Central exception handling. Maps application exceptions to HTTP status codes; AJAX / htmx /
/// SignalR-style callers get RFC 7807 problem details, regular page requests fall through to
/// the localized /Error page (re-executed by the exception handler middleware).
/// </summary>
public sealed class GlobalExceptionHandler(
    IProblemDetailsService problemDetails,
    IStringLocalizer<SharedResource> localizer,
    ILogger<GlobalExceptionHandler> logger)
    : IExceptionHandler
{
    public static int StatusCodeFor(Exception exception) => exception switch
    {
        NotFoundException => StatusCodes.Status404NotFound,
        ForbiddenAccessException => StatusCodes.Status403Forbidden,
        AppValidationException or FormValidationException or BadHttpRequestException => StatusCodes.Status400BadRequest,
        DomainException => StatusCodes.Status422UnprocessableEntity,
        DbUpdateConcurrencyException => StatusCodes.Status409Conflict,
        _ => StatusCodes.Status500InternalServerError,
    };

    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken cancellationToken)
    {
        var statusCode = StatusCodeFor(exception);
        var path = httpContext.Features.Get<IExceptionHandlerPathFeature>()?.Path ?? httpContext.Request.Path;

        // Unexpected (5xx) failures are logged with their stack trace by the exception handler
        // middleware itself; expected business failures only deserve a short warning.
        if (statusCode < 500)
        {
            logger.LogWarning("Request {Method} {Path} rejected with {StatusCode}: {Message}",
                httpContext.Request.Method, path, statusCode, exception.Message);
        }

        if (!IsApiStyleRequest(httpContext.Request))
        {
            return false; // let the middleware render the /Error page
        }

        httpContext.Response.StatusCode = statusCode;
        var problem = new ProblemDetails
        {
            Status = statusCode,
            Title = localizer[TitleFor(statusCode)].Value,
            Detail = statusCode >= 500 ? null : localizer[exception.Message].Value,
        };

        if (exception is AppValidationException validation)
        {
            problem.Extensions["errors"] = validation.Errors;
            problem.Detail = string.Join(" ", validation.Errors.SelectMany(e => e.Value).Select(m => localizer[m].Value));
        }

        return await problemDetails.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = httpContext,
            ProblemDetails = problem,
            Exception = exception,
        });
    }

    public static string TitleFor(int statusCode) => statusCode switch
    {
        400 => "The request is invalid.",
        403 => "You do not have permission to do this.",
        404 => "The requested item was not found.",
        409 => "The data was changed by someone else. Please reload and try again.",
        422 => "The operation is not allowed.",
        _ => "Something went wrong. Please try again.",
    };

    private static bool IsApiStyleRequest(HttpRequest request) =>
        request.Headers.ContainsKey("HX-Request")
        || request.Headers.XRequestedWith == "XMLHttpRequest"
        || request.Headers.Accept.Any(a => a?.Contains("application/json", StringComparison.OrdinalIgnoreCase) == true);
}
