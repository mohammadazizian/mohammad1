using Crm.Application.Common.Security;
using Crm.Application.Features.Customers;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Customers;

[HasPermission(Permissions.Modules.Customers, Permissions.Actions.View)]
public class DetailsModel : AppPageModel
{
    private const string Module = Permissions.Modules.Customers;

    public CustomerDetailsDto Customer { get; private set; } = default!;

    public bool CanEdit { get; private set; }

    public async Task OnGetAsync(Guid id) => await LoadAsync(id);

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Module, Permissions.Actions.Delete);
        if (!await TryExecuteAsync(() => Mediator.Send(new DeleteCustomerCommand(id))))
        {
            Toast(string.Join(" ", ModelState.Values.SelectMany(v => v.Errors).Select(e => e.ErrorMessage)), "danger");
            return RedirectToPage(new { id });
        }

        Toast(L["Deleted."]);
        return RedirectToPage("Index");
    }

    // ---- htmx fragments: contacts & interaction history ---------------------------------

    public async Task<IActionResult> OnPostAddContactAsync(Guid id, [FromForm] AddContactCommand contact)
    {
        await DemandAsync(Module, Permissions.Actions.Edit);
        contact.CustomerId = id;
        await Mediator.Send(contact);
        return await FragmentAsync(id, "_ContactsPartial");
    }

    public async Task<IActionResult> OnPostDeleteContactAsync(Guid id, Guid contactId)
    {
        await DemandAsync(Module, Permissions.Actions.Edit);
        await Mediator.Send(new DeleteContactCommand(contactId));
        return await FragmentAsync(id, "_ContactsPartial");
    }

    public async Task<IActionResult> OnPostAddInteractionAsync(Guid id, [FromForm] AddInteractionCommand interaction)
    {
        await DemandAsync(Module, Permissions.Actions.Edit);
        interaction.CustomerId = id;
        await Mediator.Send(interaction);
        return await FragmentAsync(id, "_InteractionsPartial");
    }

    private async Task<IActionResult> FragmentAsync(Guid id, string partial)
    {
        await LoadAsync(id);
        return Partial(partial, this);
    }

    private async Task LoadAsync(Guid id)
    {
        Customer = await Mediator.Send(new GetCustomerDetailsQuery(id));
        CanEdit = await CanAsync(Module, Permissions.Actions.Edit);
    }
}
