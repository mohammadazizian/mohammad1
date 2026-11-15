using Crm.Application.Common.Security;
using Crm.Application.Features.Deals;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Deals;

[HasPermission(Permissions.Modules.Deals, Permissions.Actions.View)]
public class DetailsModel : AppPageModel
{
    public DealDto Deal { get; private set; } = default!;

    public async Task OnGetAsync(Guid id) => Deal = await Mediator.Send(new GetDealQuery(id));

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Deals, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteDealCommand(id));
        Toast(L["Deleted."]);
        return RedirectToPage("Index");
    }
}
