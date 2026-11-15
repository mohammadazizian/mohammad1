using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Customers;
using Crm.Application.Features.Deals;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Deals;

public class EditModel : AppPageModel
{
    [BindProperty]
    public UpsertDealCommand Input { get; set; } = new();

    public IReadOnlyList<OptionDto> Customers { get; private set; } = [];

    public IReadOnlyList<StageOptionDto> Stages { get; private set; } = [];

    public bool IsNew => Input.Id is null;

    public async Task<IActionResult> OnGetAsync(Guid? id, Guid? customerId)
    {
        await DemandAsync(Permissions.Modules.Deals, id is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        await LoadOptionsAsync();

        if (id is not null)
        {
            var deal = await Mediator.Send(new GetDealQuery(id.Value));
            Input = new UpsertDealCommand
            {
                Id = deal.Id, Title = deal.Title, CustomerId = deal.CustomerId, StageId = deal.StageId, Amount = deal.Amount,
                ExpectedCloseDate = deal.ExpectedCloseDate is { } date ? Formatter.ToLocal(date).Date : null, Notes = deal.Notes,
            };
        }
        else
        {
            Input.CustomerId = customerId ?? Guid.Empty;
            Input.StageId = Stages.FirstOrDefault()?.Id ?? Guid.Empty;
        }

        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        await DemandAsync(Permissions.Modules.Deals, IsNew ? Permissions.Actions.Create : Permissions.Actions.Edit);

        // The date input carries a calendar date of the business time zone.
        Input.ExpectedCloseDate = Input.ExpectedCloseDate is { } date ? Formatter.ToUtc(date.Date.AddHours(12)) : null;

        var id = Guid.Empty;
        if (!ModelState.IsValid || !await TryExecuteAsync(async () => id = await Mediator.Send(Input)))
        {
            await LoadOptionsAsync();
            return Page();
        }

        Toast(L["Saved successfully."]);
        return RedirectToPage("Details", new { id });
    }

    private async Task LoadOptionsAsync()
    {
        Customers = await Mediator.Send(new GetCustomerOptionsQuery());
        Stages = await Mediator.Send(new GetStageOptionsQuery());
    }
}
