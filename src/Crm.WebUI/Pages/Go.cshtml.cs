using Crm.Domain.Common;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace Crm.WebUI.Pages;

/// <summary>Polymorphic permalink: /Go/{EntityType}/{id} redirects to the detail page of any trackable entity.</summary>
public class GoModel : PageModel
{
    public IActionResult OnGet(string type, Guid id) =>
        EntityRef.TryParse($"{type}:{id}", out var entity) ? LocalRedirect(EntityRoutes.Url(entity)) : NotFound();
}
