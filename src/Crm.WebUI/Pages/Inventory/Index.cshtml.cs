using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Inventory;
using Crm.Domain.Inventory;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Inventory;

[HasPermission(Permissions.Modules.Inventory, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    [BindProperty(SupportsGet = true)]
    public StockMovementType? Type { get; set; }

    [BindProperty(SupportsGet = true)]
    public Guid? ProductId { get; set; }

    [BindProperty(SupportsGet = true, Name = "p")]
    public int PageNumber { get; set; } = 1;

    public PagedList<InventoryTransactionDto> Transactions { get; private set; } = default!;

    public async Task<IActionResult> OnGetAsync()
    {
        Transactions = await Mediator.Send(new GetInventoryTransactionsQuery { Search = Q, Type = Type, ProductId = ProductId, Page = PageNumber });
        return IsHtmx ? Partial("_ListPartial", this) : Page();
    }
}
