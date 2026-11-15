using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Admin.Users;

[HasPermission(Permissions.Modules.Users, Permissions.Actions.View)]
public class IndexModel(IIdentityService identity) : AppPageModel
{
    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    public IReadOnlyList<UserSummary> Users { get; private set; } = [];

    public async Task<IActionResult> OnGetAsync()
    {
        Users = await identity.GetUsersAsync(Q, cancellationToken: HttpContext.RequestAborted);
        return IsHtmx ? Partial("_ListPartial", this) : Page();
    }
}
