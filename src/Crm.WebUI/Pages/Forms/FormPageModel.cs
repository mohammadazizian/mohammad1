using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using Crm.WebUI.Support;

namespace Crm.WebUI.Pages.Forms;

/// <summary>Base of the data-entry pages of dynamic forms: enforces the per-form permissions.</summary>
public abstract class FormPageModel : AppPageModel
{
    public FormDto Form { get; protected set; } = default!;

    public Task<bool> CanFormAsync(string action) => CanAsync(Permissions.FormModule(Form.Code), action);

    protected Task DemandFormAsync(string action) => DemandAsync(Permissions.FormModule(Form.Code), action);

    protected async Task LoadFormAsync(string code, string action)
    {
        Form = await Mediator.Send(new GetFormQuery(Code: code));
        await DemandFormAsync(action);
    }
}
