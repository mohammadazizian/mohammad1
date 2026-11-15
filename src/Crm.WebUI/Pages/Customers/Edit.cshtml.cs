using Crm.Application.Common.Security;
using Crm.Application.Features.Customers;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Customers;

public class EditModel : AppPageModel
{
    [BindProperty]
    public UpsertCustomerCommand Input { get; set; } = new();

    public bool IsNew => Input.Id is null;

    public async Task<IActionResult> OnGetAsync(Guid? id)
    {
        await DemandAsync(Permissions.Modules.Customers, id is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        if (id is not null)
        {
            var customer = await Mediator.Send(new GetCustomerDetailsQuery(id.Value));
            Input = new UpsertCustomerCommand
            {
                Id = customer.Id, Name = customer.Name, Type = customer.Type, Email = customer.Email, Phone = customer.Phone,
                TaxId = customer.TaxId, Notes = customer.Notes, Street = customer.Address.Street, City = customer.Address.City,
                Country = customer.Address.Country, PostalCode = customer.Address.PostalCode,
            };
        }

        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        await DemandAsync(Permissions.Modules.Customers, IsNew ? Permissions.Actions.Create : Permissions.Actions.Edit);

        var id = Guid.Empty;
        if (!ModelState.IsValid || !await TryExecuteAsync(async () => id = await Mediator.Send(Input)))
        {
            return Page();
        }

        Toast(L["Saved successfully."]);
        return RedirectToPage("Details", new { id });
    }
}
