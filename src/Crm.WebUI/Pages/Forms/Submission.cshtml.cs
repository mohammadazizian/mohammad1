using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Forms;

/// <summary>A submitted form - a first-class trackable object with chat, tasks, reminders and activity.</summary>
public class SubmissionModel : FormPageModel
{
    public SubmissionDto Submission { get; private set; } = default!;

    public bool CanEdit { get; private set; }

    public bool CanDelete { get; private set; }

    public async Task OnGetAsync(Guid id)
    {
        await LoadAsync(id, Permissions.Actions.View);
        CanEdit = await CanFormAsync(Permissions.Actions.Edit);
        CanDelete = await CanFormAsync(Permissions.Actions.Delete);
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await LoadAsync(id, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteSubmissionCommand(id));
        Toast(L["Deleted."]);
        return RedirectToPage("Submissions", new { code = Form.Code });
    }

    private async Task LoadAsync(Guid id, string action)
    {
        Submission = await Mediator.Send(new GetSubmissionQuery(id));
        Form = Submission.Form;
        await DemandFormAsync(action);
    }
}
