using Crm.Application.Common.Security;
using Crm.Application.Features.Products;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Products;

[HasPermission(Permissions.Modules.Products, Permissions.Actions.View)]
public class CategoriesModel : AppPageModel
{
    public IReadOnlyList<CategoryDto> Categories { get; private set; } = [];

    public bool CanEdit { get; private set; }

    public async Task OnGetAsync() => await LoadAsync();

    public async Task<IActionResult> OnPostSaveAsync([FromForm] UpsertCategoryCommand category)
    {
        await DemandAsync(Permissions.Modules.Products, Permissions.Actions.Edit);
        await Mediator.Send(category);
        return await ListAsync();
    }

    public async Task<IActionResult> OnPostDeleteAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Products, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteCategoryCommand(id));
        return await ListAsync();
    }

    private async Task<IActionResult> ListAsync()
    {
        await LoadAsync();
        return Partial("_CategoryListPartial", this);
    }

    private async Task LoadAsync()
    {
        Categories = await Mediator.Send(new GetCategoriesQuery());
        CanEdit = await CanAsync(Permissions.Modules.Products, Permissions.Actions.Edit);
    }
}
