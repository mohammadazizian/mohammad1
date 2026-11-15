using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Collaboration;
using Crm.Domain.Collaboration;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Pages.Collab;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Tasks;

[HasPermission(Permissions.Modules.Tasks, Permissions.Actions.View)]
public class IndexModel(IIdentityService identity) : AppPageModel
{
    private const string Module = Permissions.Modules.Tasks;

    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    [BindProperty(SupportsGet = true)]
    public TaskScope Scope { get; set; } = TaskScope.Mine;

    [BindProperty(SupportsGet = true)]
    public bool OpenOnly { get; set; } = true;

    [BindProperty(SupportsGet = true, Name = "p")]
    public int PageNumber { get; set; } = 1;

    public PagedList<TaskDto> Tasks { get; private set; } = default!;

    public TaskFormViewModel Form { get; private set; } = new([], [], "nt");

    public bool CanEdit { get; private set; }

    public bool CanDelete { get; private set; }

    public async Task<IActionResult> OnGetAsync()
    {
        await LoadAsync();
        if (IsHtmx)
        {
            return Partial("_ListPartial", this);
        }

        var (users, roles) = await TaskInput.LoadAssigneesAsync(identity, HttpContext.RequestAborted);
        Form = new TaskFormViewModel(users, roles, "nt");
        return Page();
    }

    public async Task<IActionResult> OnPostCreateAsync([FromForm] TaskInput input)
    {
        await DemandAsync(Module, Permissions.Actions.Create);
        await Mediator.Send(input.ToCommand(Formatter));
        HxToast(L["Task created."]);
        return await ListAsync();
    }

    public async Task<IActionResult> OnPostStatusAsync(Guid id, TaskItemStatus status)
    {
        await DemandAsync(Module, Permissions.Actions.Edit);
        await Mediator.Send(new ChangeTaskStatusCommand(id, status));
        return await ListAsync();
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Module, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteTaskCommand(id));
        return await ListAsync();
    }

    private async Task<IActionResult> ListAsync()
    {
        await LoadAsync();
        return Partial("_ListPartial", this);
    }

    private async Task LoadAsync()
    {
        Tasks = await Mediator.Send(new GetTasksQuery { Search = Q, Scope = Scope, OpenOnly = OpenOnly, Page = PageNumber, PageSize = 20 });
        CanEdit = await CanAsync(Module, Permissions.Actions.Edit);
        CanDelete = await CanAsync(Module, Permissions.Actions.Delete);
    }

    /// <summary>Query string that preserves the current filters for htmx posts.</summary>
    public string FilterQuery => $"scope={Scope}&openOnly={OpenOnly.ToString().ToLowerInvariant()}&q={Uri.EscapeDataString(Q ?? string.Empty)}&p={PageNumber}";
}
