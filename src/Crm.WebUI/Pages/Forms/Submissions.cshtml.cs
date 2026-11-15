using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Forms;

public class SubmissionsModel : FormPageModel
{
    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    [BindProperty(SupportsGet = true, Name = "p")]
    public int PageNumber { get; set; } = 1;

    public PagedList<SubmissionListItem> Submissions { get; private set; } = default!;

    public bool CanCreate { get; private set; }

    public async Task<IActionResult> OnGetAsync(string code)
    {
        await LoadFormAsync(code, Permissions.Actions.View);
        Submissions = await Mediator.Send(new GetSubmissionsQuery { FormId = Form.Id, Search = Q, Page = PageNumber });
        CanCreate = Form.IsPublished && await CanFormAsync(Permissions.Actions.Create);
        return IsHtmx ? Partial("_SubmissionListPartial", this) : Page();
    }
}
