using Crm.Application.Common.Security;
using Crm.Application.Features.Deals;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Deals;

[HasPermission(Permissions.Modules.Deals, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    public DealBoardDto Board { get; private set; } = default!;

    public bool CanMove { get; private set; }

    public async Task<IActionResult> OnGetAsync()
    {
        await LoadAsync();
        return IsHtmx ? Partial("_BoardPartial", this) : Page();
    }

    /// <summary>Kanban drag &amp; drop: moves a deal to another stage and returns the refreshed board.</summary>
    public async Task<IActionResult> OnPostMoveAsync(Guid dealId, Guid stageId)
    {
        await DemandAsync(Permissions.Modules.Deals, Permissions.Actions.Edit);
        await Mediator.Send(new MoveDealCommand(dealId, stageId));
        await LoadAsync();
        return Partial("_BoardPartial", this);
    }

    private async Task LoadAsync()
    {
        Board = await Mediator.Send(new GetDealBoardQuery());
        CanMove = await CanAsync(Permissions.Modules.Deals, Permissions.Actions.Edit);
    }
}
