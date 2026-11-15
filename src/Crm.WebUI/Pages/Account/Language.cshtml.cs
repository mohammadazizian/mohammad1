using Crm.WebUI.Support;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.Extensions.Options;

namespace Crm.WebUI.Pages.Account;

/// <summary>Language switcher endpoint: remembers the chosen UI culture in a cookie.</summary>
public class LanguageModel(IOptions<RequestLocalizationOptions> options) : PageModel
{
    public IActionResult OnGet() => LocalRedirect("/");

    public IActionResult OnPost(string culture, string? returnUrl)
    {
        var supported = options.Value.SupportedUICultures ?? [];
        if (supported.Any(c => string.Equals(c.Name, culture, StringComparison.OrdinalIgnoreCase)))
        {
            LanguageCookie.Write(Response, culture);
        }

        return LocalRedirect(Url.IsLocalUrl(returnUrl) ? returnUrl : "/");
    }
}
