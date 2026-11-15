using Crm.Application.Common.Security;
using Crm.Application.Features.Inventory;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;

namespace Crm.WebUI.Pages.Inventory;

[HasPermission(Permissions.Modules.Inventory, Permissions.Actions.View)]
public class DetailsModel : AppPageModel
{
    public InventoryTransactionDto Transaction { get; private set; } = default!;

    public async Task OnGetAsync(Guid id) => Transaction = await Mediator.Send(new GetInventoryTransactionQuery(id));
}
