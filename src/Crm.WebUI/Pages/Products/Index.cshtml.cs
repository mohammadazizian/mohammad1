using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Products;
using Crm.Infrastructure.Identity;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Products;

[HasPermission(Permissions.Modules.Products, Permissions.Actions.View)]
public class IndexModel : AppPageModel
{
    [BindProperty(SupportsGet = true)]
    public string? Q { get; set; }

    [BindProperty(SupportsGet = true)]
    public Guid? CategoryId { get; set; }

    [BindProperty(SupportsGet = true)]
    public bool LowStock { get; set; }

    [BindProperty(SupportsGet = true, Name = "p")]
    public int PageNumber { get; set; } = 1;

    public PagedList<ProductListItem> Products { get; private set; } = default!;

    public IReadOnlyList<CategoryDto> Categories { get; private set; } = [];

    public async Task<IActionResult> OnGetAsync()
    {
        Products = await Mediator.Send(new GetProductsQuery { Search = Q, CategoryId = CategoryId, LowStockOnly = LowStock, Page = PageNumber });
        if (IsHtmx)
        {
            return Partial("_ListPartial", this);
        }

        Categories = await Mediator.Send(new GetCategoriesQuery());
        return Page();
    }
}
