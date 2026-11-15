using Crm.Application.Common.Security;
using Crm.Application.Features.Leads;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Leads;

[HasPermission(Permissions.Modules.Leads, Permissions.Actions.View)]
public class DetailsModel : AppPageModel
{
    public LeadDto Lead { get; private set; } = default!;

    public async Task OnGetAsync(Guid id) => Lead = await Mediator.Send(new GetLeadQuery(id));

    /// <summary>Lead → customer conversion; needs the right to edit leads and to create customers.</summary>
    public async Task<IActionResult> OnPostConvertAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Leads, Permissions.Actions.Edit);
        await DemandAsync(Permissions.Modules.Customers, Permissions.Actions.Create);

        var customerId = Guid.Empty;
        if (!await TryExecuteAsync(async () => customerId = await Mediator.Send(new ConvertLeadCommand(id))))
        {
            Toast(string.Join(" ", ModelState.Values.SelectMany(v => v.Errors).Select(e => e.ErrorMessage)), "danger");
            return RedirectToPage(new { id });
        }

        Toast(L["Lead converted to customer."]);
        return RedirectToPage("/Customers/Details", new { id = customerId });
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Leads, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteLeadCommand(id));
        Toast(L["Deleted."]);
        return RedirectToPage("Index");
    }
}
