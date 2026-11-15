using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.FormBuilder;

[HasPermission(Permissions.Modules.Forms, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    public IReadOnlyList<FormSummaryDto> Forms { get; private set; } = [];

    public async Task OnGetAsync() => Forms = await Mediator.Send(new GetFormsQuery());

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Forms, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteFormCommand(id));
        Toast(L["Deleted."]);
        return RedirectToPage();
    }
}
