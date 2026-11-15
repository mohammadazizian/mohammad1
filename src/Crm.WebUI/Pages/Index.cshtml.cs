using Crm.Application.Common.Security;
using Crm.Application.Features.Dashboard;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;

namespace Crm.WebUI.Pages;

[HasPermission(Permissions.Modules.Dashboard, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    public DashboardDto Dashboard { get; private set; } = default!;

    public async Task OnGetAsync() => Dashboard = await Mediator.Send(new GetDashboardQuery());
}
