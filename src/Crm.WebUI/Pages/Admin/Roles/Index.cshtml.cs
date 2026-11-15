using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Admin.Roles;

[HasPermission(Permissions.Modules.Roles, Permissions.Actions.View)]
public class IndexModel(IIdentityService identity) : AppPageModel
{
    public IReadOnlyList<RoleSummary> Roles { get; private set; } = [];

    public async Task OnGetAsync() => Roles = await identity.GetRolesAsync(HttpContext.RequestAborted);

    public async Task<IActionResult> OnPostCreateAsync(string name, string? description)
    {
        await DemandAsync(Permissions.Modules.Roles, Permissions.Actions.Create);
        var result = string.IsNullOrWhiteSpace(name)
            ? IdentityResultDto.Failure([L["The {0} field is required.", L["Name"]]])
            : await identity.CreateRoleAsync(name, description, HttpContext.RequestAborted);
        return Finish(result, L["Saved successfully."]);
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Roles, Permissions.Actions.Delete);
        return Finish(await identity.DeleteRoleAsync(id, HttpContext.RequestAborted), L["Deleted."]);
    }

    private IActionResult Finish(IdentityResultDto result, string success)
    {
        if (result.Succeeded)
        {
            Toast(success);
        }
        else
        {
            Toast(string.Join(" ", result.Errors.Select(e => L[e].Value)), "danger");
        }

        return RedirectToPage();
    }
}
