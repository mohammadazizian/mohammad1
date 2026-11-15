using System.Text.Json;
using Crm.Application.Common.Exceptions;
using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.Domain.Common;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Localization;

namespace Crm.WebUI.Support;

/// <summary>
/// Base class of all page models: MediatR access, permission checks, uniform translation of
/// application errors into ModelState, and toast notifications (full-page and htmx).
/// </summary>
public abstract class AppPageModel : PageModel
{
    public const string ToastKey = "Toast";

    protected ISender Mediator => field ??= HttpContext.RequestServices.GetRequiredService<ISender>();

    protected IStringLocalizer<SharedResource> L => field ??= HttpContext.RequestServices.GetRequiredService<IStringLocalizer<SharedResource>>();

    protected ILocalizedFormatter Formatter => field ??= HttpContext.RequestServices.GetRequiredService<ILocalizedFormatter>();

    /// <summary>True when the request was issued by htmx and expects an HTML fragment.</summary>
    public bool IsHtmx =>
        Request.Headers.ContainsKey("HX-Request") && !Request.Headers.ContainsKey("HX-History-Restore-Request");

    public async Task<bool> CanAsync(string module, string action)
    {
        var authorization = HttpContext.RequestServices.GetRequiredService<IAuthorizationService>();
        var result = await authorization.AuthorizeAsync(User, Permissions.PolicyPrefix + Permissions.For(module, action));
        return result.Succeeded;
    }

    /// <summary>Throws <see cref="ForbiddenAccessException"/> (→ HTTP 403) unless the user holds the permission.</summary>
    protected async Task DemandAsync(string module, string action)
    {
        if (!await CanAsync(module, action))
        {
            throw new ForbiddenAccessException();
        }
    }

    /// <summary>
    /// Runs a command and converts validation / business-rule failures into ModelState errors.
    /// Returns true when the command succeeded.
    /// </summary>
    protected async Task<bool> TryExecuteAsync(Func<Task> action, string prefix = "Input")
    {
        try
        {
            await action();
            return true;
        }
        catch (AppValidationException ex)
        {
            foreach (var (property, messages) in ex.Errors)
            {
                foreach (var message in messages)
                {
                    ModelState.AddModelError(string.IsNullOrEmpty(prefix) ? property : $"{prefix}.{property}", L[message]);
                }
            }
        }
        catch (DomainException ex)
        {
            ModelState.AddModelError(string.Empty, L[ex.Message]);
        }
        catch (DbUpdateConcurrencyException)
        {
            ModelState.AddModelError(string.Empty, L[GlobalExceptionHandler.TitleFor(StatusCodes.Status409Conflict)]);
        }

        return false;
    }

    /// <summary>Shows a toast after the next full page load (survives a redirect).</summary>
    protected void Toast(string message, string type = "success") =>
        TempData[ToastKey] = JsonSerializer.Serialize(new { message, type });

    /// <summary>Shows a toast as part of an htmx response (HX-Trigger header).</summary>
    protected void HxToast(string message, string type = "success") =>
        Response.Headers["HX-Trigger"] = JsonSerializer.Serialize(new { toast = new { message = Uri.EscapeDataString(message), type } });

    /// <summary>Asks htmx to navigate the browser (used after a successful htmx form post).</summary>
    protected void HxRedirect(string url) => Response.Headers["HX-Redirect"] = url;
}
