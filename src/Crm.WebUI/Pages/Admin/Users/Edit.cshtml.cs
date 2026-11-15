using System.ComponentModel.DataAnnotations;
using Crm.Application.Common.Exceptions;
using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Admin.Users;

public class EditModel(IIdentityService identity) : AppPageModel
{
    [BindProperty]
    public InputModel Input { get; set; } = new();

    public IReadOnlyList<RoleSummary> Roles { get; private set; } = [];

    public bool IsNew => Input.Id is null;

    public async Task<IActionResult> OnGetAsync(Guid? id)
    {
        await DemandAsync(Permissions.Modules.Users, id is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        Roles = await identity.GetRolesAsync(HttpContext.RequestAborted);

        if (id is not null)
        {
            var user = await identity.GetUserAsync(id.Value, HttpContext.RequestAborted) ?? throw new NotFoundException("User", id.Value);
            Input = new InputModel
            {
                Id = user.Id, UserName = user.UserName, FullName = user.FullName, Email = user.Email,
                IsActive = user.IsActive, Roles = [.. user.Roles],
            };
        }

        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        await DemandAsync(Permissions.Modules.Users, IsNew ? Permissions.Actions.Create : Permissions.Actions.Edit);
        Roles = await identity.GetRolesAsync(HttpContext.RequestAborted);

        if (IsNew && string.IsNullOrEmpty(Input.Password))
        {
            ModelState.AddModelError("Input.Password", L["The {0} field is required.", L["Password"]]);
        }

        // An administrator must not lock themselves out by accident.
        if (Input.Id == HttpContext.RequestServices.GetRequiredService<ICurrentUser>().UserId
            && (!Input.IsActive || (User.IsInRole(Permissions.AdministratorRole) && !Input.Roles.Contains(Permissions.AdministratorRole))))
        {
            ModelState.AddModelError(string.Empty, L["You cannot deactivate yourself or remove your own administrator role."]);
        }

        if (!ModelState.IsValid)
        {
            return Page();
        }

        var result = await identity.SaveUserAsync(
            new SaveUserRequest(Input.Id, Input.UserName, Input.FullName, Input.Email, Input.Password, Input.IsActive, Input.Roles),
            HttpContext.RequestAborted);

        if (!result.Succeeded)
        {
            foreach (var error in result.Errors)
            {
                ModelState.AddModelError(string.Empty, error);
            }

            return Page();
        }

        Toast(L["Saved successfully."]);
        return RedirectToPage("Index");
    }

    public sealed class InputModel
    {
        public Guid? Id { get; set; }

        [Required(ErrorMessage = "The {0} field is required.")]
        [RegularExpression("^[A-Za-z0-9._-]{2,64}$", ErrorMessage = "Use 2-64 Latin letters, digits, dots, dashes or underscores.")]
        [Display(Name = "User name")]
        public string UserName { get; set; } = string.Empty;

        [Required(ErrorMessage = "The {0} field is required.")]
        [StringLength(200)]
        [Display(Name = "Full name")]
        public string FullName { get; set; } = string.Empty;

        [EmailAddress(ErrorMessage = "The {0} field is not a valid e-mail address.")]
        [Display(Name = "Email")]
        public string? Email { get; set; }

        [DataType(DataType.Password)]
        [Display(Name = "Password")]
        public string? Password { get; set; }

        [Display(Name = "Active")]
        public bool IsActive { get; set; } = true;

        public List<string> Roles { get; set; } = [];
    }
}
