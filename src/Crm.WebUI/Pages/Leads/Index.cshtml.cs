using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Leads;
using Crm.Domain.Sales;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Leads;

[HasPermission(Permissions.Modules.Leads, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    [BindProperty(SupportsGet = true)]
    public LeadStatus? Status { get; set; }

    [BindProperty(SupportsGet = true, Name = "p")]
    public int PageNumber { get; set; } = 1;

    public PagedList<LeadDto> Leads { get; private set; } = default!;

    public async Task<IActionResult> OnGetAsync()
    {
        Leads = await Mediator.Send(new GetLeadsQuery { Search = Q, Status = Status, Page = PageNumber });
        return IsHtmx ? Partial("_ListPartial", this) : Page();
    }
}
