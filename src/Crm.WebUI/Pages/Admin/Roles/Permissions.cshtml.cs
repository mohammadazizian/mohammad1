using Crm.Application.Common.Exceptions;
using Crm.Application.Common.Interfaces;
using Crm.Application.Features.Forms;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;
using P = Crm.Application.Common.Security.Permissions;

namespace Crm.WebUI.Pages.Admin.Roles;

/// <summary>
/// Permission matrix of one role: modules × actions plus one row per dynamic form.
/// Changes take effect immediately (the permission cache entry of the role is dropped).
/// </summary>
[HasPermission(P.Modules.Roles, P.Actions.View)]
public class PermissionsModel(IIdentityService identity, ICultureContext culture) : AppPageModel
{
    public sealed record Row(string Module, string Label, bool IsForm);

    public RoleSummary Role { get; private set; } = default!;

    public IReadOnlyList<Row> Rows { get; private set; } = [];

    public IReadOnlySet<string> Granted { get; private set; } = new HashSet<string>();

    public bool IsAdministrator => Role.Name == P.AdministratorRole;

    public bool CanEdit { get; private set; }

    public async Task OnGetAsync(Guid id) => await LoadAsync(id);

    public async Task<IActionResult> OnPostAsync(Guid id, List<string> permissions)
    {
        await DemandAsync(P.Modules.Roles, P.Actions.Edit);
        await LoadAsync(id);

        // Accept only permissions that exist in the catalogue (static modules + current forms).
        var valid = Rows.SelectMany(r => P.Actions.All.Select(a => P.For(r.Module, a))).ToHashSet();
        await identity.SetRolePermissionsAsync(id, permissions.Where(valid.Contains), HttpContext.RequestAborted);

        Toast(L["Permissions updated."]);
        return RedirectToPage(new { id });
    }

    private async Task LoadAsync(Guid id)
    {
        Role = await identity.GetRoleAsync(id, HttpContext.RequestAborted) ?? throw new NotFoundException("Role", id);
        Granted = await identity.GetRolePermissionsAsync(id, HttpContext.RequestAborted);
        CanEdit = !IsAdministrator && await CanAsync(P.Modules.Roles, P.Actions.Edit);

        var forms = await Mediator.Send(new GetFormsQuery());
        Rows =
        [
            .. P.Modules.All.Select(m => new Row(m, L["Module_" + m].ResourceNotFound ? L.Field(m) : L["Module_" + m], false)),
            .. forms.Select(f => new Row(P.FormModule(f.Code), f.Title.Get(culture.CultureName), true)),
        ];
    }
}
