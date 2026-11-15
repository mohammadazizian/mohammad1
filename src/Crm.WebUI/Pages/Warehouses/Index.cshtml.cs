using Crm.Application.Common.Security;
using Crm.Application.Features.Products;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Warehouses;

[HasPermission(Permissions.Modules.Inventory, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    public IReadOnlyList<WarehouseDto> Warehouses { get; private set; } = [];

    public bool CanEdit { get; private set; }

    public async Task OnGetAsync() => await LoadAsync();

    public async Task<IActionResult> OnPostSaveAsync([FromForm] UpsertWarehouseCommand warehouse)
    {
        await DemandAsync(Permissions.Modules.Inventory, Permissions.Actions.Edit);
        await Mediator.Send(warehouse);
        return await ListAsync();
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Inventory, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteWarehouseCommand(id));
        return await ListAsync();
    }

    private async Task<IActionResult> ListAsync()
    {
        await LoadAsync();
        return Partial("_WarehouseListPartial", this);
    }

    private async Task LoadAsync()
    {
        Warehouses = await Mediator.Send(new GetWarehousesQuery());
        CanEdit = await CanAsync(Permissions.Modules.Inventory, Permissions.Actions.Edit);
    }
}
