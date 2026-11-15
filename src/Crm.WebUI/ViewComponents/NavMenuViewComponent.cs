using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.ViewComponents;

public sealed record NavItem(string Text, string Url, string Icon, string ActivePrefix, bool Localize = true);

public sealed record NavSection(string? Title, IReadOnlyList<NavItem> Items);

/// <summary>
/// Sidebar navigation. Entries are filtered by the user's permissions and every published
/// dynamic form the user may view gets its own entry - no code change needed for new forms.
/// </summary>
public sealed class NavMenuViewComponent(IAuthorizationService authorization, ISender mediator, ICultureContext culture)
    : ViewComponent
{
    private static readonly (string? Section, string Text, string Url, string Icon, string Module)[] StaticItems =
    [
        (null, "Dashboard", "/", "bi-grid-1x2", Permissions.Modules.Dashboard),
        ("CRM", "Leads", "/Leads", "bi-person-plus", Permissions.Modules.Leads),
        ("CRM", "Customers", "/Customers", "bi-building", Permissions.Modules.Customers),
        ("CRM", "Deals", "/Deals", "bi-kanban", Permissions.Modules.Deals),
        ("Inventory", "Products", "/Products", "bi-box-seam", Permissions.Modules.Products),
        ("Inventory", "Stock movements", "/Inventory", "bi-arrow-left-right", Permissions.Modules.Inventory),
        ("Inventory", "Warehouses", "/Warehouses", "bi-houses", Permissions.Modules.Inventory),
        ("Workspace", "Tasks", "/Tasks", "bi-check2-square", Permissions.Modules.Tasks),
        ("Workspace", "Reports", "/Reports", "bi-bar-chart", Permissions.Modules.Reports),
        ("Administration", "Form builder", "/FormBuilder", "bi-ui-checks-grid", Permissions.Modules.Forms),
        ("Administration", "Users", "/Admin/Users", "bi-people", Permissions.Modules.Users),
        ("Administration", "Roles & permissions", "/Admin/Roles", "bi-shield-lock", Permissions.Modules.Roles),
    ];

    public async Task<IViewComponentResult> InvokeAsync()
    {
        var sections = new List<NavSection>();

        foreach (var group in StaticItems.GroupBy(i => i.Section))
        {
            var items = new List<NavItem>();
            foreach (var item in group)
            {
                if (await CanAsync(Permissions.For(item.Module, Permissions.Actions.View)))
                {
                    items.Add(new NavItem(item.Text, item.Url, item.Icon, item.Url));
                }
            }

            if (items.Count != 0)
            {
                sections.Add(new NavSection(group.Key, items));
            }
        }

        var formItems = new List<NavItem>();
        foreach (var form in await mediator.Send(new GetFormsQuery(PublishedOnly: true)))
        {
            if (await CanAsync(Permissions.ForForm(form.Code, Permissions.Actions.View)))
            {
                var url = $"/Forms/Submissions/{form.Code}";
                formItems.Add(new NavItem(form.Title.Get(culture.CultureName), url, "bi-ui-checks", url, Localize: false));
            }
        }

        if (formItems.Count != 0)
        {
            var index = sections.FindIndex(s => s.Title == "Administration");
            sections.Insert(index < 0 ? sections.Count : index, new NavSection("Forms", formItems));
        }

        return View(sections);
    }

    private async Task<bool> CanAsync(string permission) =>
        (await authorization.AuthorizeAsync(UserClaimsPrincipal, Permissions.PolicyPrefix + permission)).Succeeded;
}
