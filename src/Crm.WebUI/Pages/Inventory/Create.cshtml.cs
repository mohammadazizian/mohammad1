using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Inventory;
using Crm.Application.Features.Products;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Inventory;

[HasPermission(Permissions.Modules.Inventory, Permissions.Actions.Create)]
public class CreateModel : AppPageModel
{
    [BindProperty]
    public CreateInventoryTransactionCommand Input { get; set; } = new();

    public IReadOnlyList<OptionDto> Products { get; private set; } = [];

    public IReadOnlyList<WarehouseDto> Warehouses { get; private set; } = [];

    public async Task OnGetAsync(Guid? productId)
    {
        await LoadOptionsAsync();
        Input.ProductId = productId ?? Guid.Empty;
    }

    public async Task<IActionResult> OnPostAsync()
    {
        var id = Guid.Empty;
        if (!ModelState.IsValid || !await TryExecuteAsync(async () => id = await Mediator.Send(Input)))
        {
            await LoadOptionsAsync();
            return Page();
        }

        Toast(L["Stock movement recorded."]);
        return RedirectToPage("Details", new { id });
    }

    private async Task LoadOptionsAsync()
    {
        Products = await Mediator.Send(new GetProductOptionsQuery());
        Warehouses = await Mediator.Send(new GetWarehousesQuery());
    }
}
