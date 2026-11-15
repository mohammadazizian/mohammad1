using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Inventory;
using Crm.Application.Features.Products;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Products;

[HasPermission(Permissions.Modules.Products, Permissions.Actions.View)]
public class DetailsModel : AppPageModel
{
    public ProductDetailsDto Product { get; private set; } = default!;

    public IReadOnlyList<InventoryTransactionDto> RecentMovements { get; private set; } = [];

    public async Task OnGetAsync(Guid id)
    {
        Product = await Mediator.Send(new GetProductDetailsQuery(id));
        if (await CanAsync(Permissions.Modules.Inventory, Permissions.Actions.View))
        {
            RecentMovements = (await Mediator.Send(new GetInventoryTransactionsQuery { ProductId = id, PageSize = 8 })).Items;
        }
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Products, Permissions.Actions.Delete);
        if (!await TryExecuteAsync(() => Mediator.Send(new DeleteProductCommand(id))))
        {
            Toast(string.Join(" ", ModelState.Values.SelectMany(v => v.Errors).Select(e => e.ErrorMessage)), "danger");
            return RedirectToPage(new { id });
        }

        Toast(L["Deleted."]);
        return RedirectToPage("Index");
    }
}
