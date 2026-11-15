using Crm.WebUI.Support;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace Crm.WebUI.Pages;

/// <summary>Friendly, localized error page for both exceptions and plain status codes (404, 403, ...).</summary>
[ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
[IgnoreAntiforgeryToken]
public class ErrorModel : PageModel
{
    public int Status { get; private set; }

    public string Message { get; private set; } = string.Empty;

    public string? RequestId { get; private set; }

    public void OnGet(int? code) => Prepare(code);

    public void OnPost(int? code) => Prepare(code);

    private void Prepare(int? code)
    {
        var exception = HttpContext.Features.Get<IExceptionHandlerFeature>()?.Error;
        Status = exception is not null ? GlobalExceptionHandler.StatusCodeFor(exception) : code ?? Response.StatusCode;
        if (Status < 400)
        {
            Status = StatusCodes.Status500InternalServerError;
        }

        Message = GlobalExceptionHandler.TitleFor(Status);
        RequestId = HttpContext.TraceIdentifier;
    }
}
