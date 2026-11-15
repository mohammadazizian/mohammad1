using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Customers;
using Crm.Domain.Sales;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Customers;

[HasPermission(Permissions.Modules.Customers, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    [BindProperty(SupportsGet = true)]
    public CustomerType? Type { get; set; }

    [BindProperty(SupportsGet = true, Name = "p")]
    public int PageNumber { get; set; } = 1;

    public PagedList<CustomerListItem> Customers { get; private set; } = default!;

    public async Task<IActionResult> OnGetAsync()
    {
        Customers = await Mediator.Send(new GetCustomersQuery { Search = Q, Type = Type, Page = PageNumber });
        return IsHtmx ? Partial("_ListPartial", this) : Page();
    }
}
