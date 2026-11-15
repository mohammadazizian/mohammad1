using Crm.Application.Common.Security;
using Crm.Application.Features.Leads;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Leads;

public class EditModel : AppPageModel
{
    [BindProperty]
    public UpsertLeadCommand Input { get; set; } = new();

    public bool IsNew => Input.Id is null;

    public async Task<IActionResult> OnGetAsync(Guid? id)
    {
        await DemandAsync(Permissions.Modules.Leads, id is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        if (id is not null)
        {
            var lead = await Mediator.Send(new GetLeadQuery(id.Value));
            Input = new UpsertLeadCommand
            {
                Id = lead.Id, Name = lead.Name, Company = lead.Company, Email = lead.Email, Phone = lead.Phone,
                Source = lead.Source, Status = lead.Status, EstimatedValue = lead.EstimatedValue, Notes = lead.Notes,
            };
        }

        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        await DemandAsync(Permissions.Modules.Leads, IsNew ? Permissions.Actions.Create : Permissions.Actions.Edit);

        var id = Guid.Empty;
        if (!ModelState.IsValid || !await TryExecuteAsync(async () => id = await Mediator.Send(Input)))
        {
            return Page();
        }

        Toast(L["Saved successfully."]);
        return RedirectToPage("Details", new { id });
    }
}
