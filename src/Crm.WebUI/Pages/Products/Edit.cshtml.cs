using Crm.Application.Common.Security;
using Crm.Application.Features.Products;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Products;

public class EditModel : AppPageModel
{
    [BindProperty]
    public UpsertProductCommand Input { get; set; } = new();

    public IReadOnlyList<CategoryDto> Categories { get; private set; } = [];

    public bool IsNew => Input.Id is null;

    public async Task<IActionResult> OnGetAsync(Guid? id)
    {
        await DemandAsync(Permissions.Modules.Products, id is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        Categories = await Mediator.Send(new GetCategoriesQuery());

        if (id is not null)
        {
            var product = await Mediator.Send(new GetProductDetailsQuery(id.Value));
            Input = new UpsertProductCommand
            {
                Id = product.Id, Sku = product.Sku, Name = product.Name, Description = product.Description,
                CategoryId = product.CategoryId, UnitPrice = product.UnitPrice, Cost = product.Cost, Unit = product.Unit,
                LowStockThreshold = product.LowStockThreshold, IsActive = product.IsActive,
            };
        }

        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        await DemandAsync(Permissions.Modules.Products, IsNew ? Permissions.Actions.Create : Permissions.Actions.Edit);

        var id = Guid.Empty;
        if (!ModelState.IsValid || !await TryExecuteAsync(async () => id = await Mediator.Send(Input)))
        {
            Categories = await Mediator.Send(new GetCategoriesQuery());
            return Page();
        }

        Toast(L["Saved successfully."]);
        return RedirectToPage("Details", new { id });
    }
}
