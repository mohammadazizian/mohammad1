using System.ComponentModel.DataAnnotations;
using Crm.Application.Common.Interfaces;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.Extensions.Localization;

namespace Crm.WebUI.Pages.Account;

public class LoginModel(ISignInService signIn, IStringLocalizer<SharedResource> localizer) : PageModel
{
    [BindProperty]
    public InputModel Input { get; set; } = new();

    [BindProperty(SupportsGet = true)]
    public string? ReturnUrl { get; set; }

    public IActionResult OnGet() =>
        User.Identity?.IsAuthenticated == true ? LocalRedirect(SafeReturnUrl()) : Page();

    public async Task<IActionResult> OnPostAsync()
    {
        if (!ModelState.IsValid)
        {
            return Page();
        }

        var outcome = await signIn.PasswordSignInAsync(Input.UserName, Input.Password, Input.RememberMe);
        if (outcome == SignInOutcome.Succeeded)
        {
            return LocalRedirect(SafeReturnUrl());
        }

        ModelState.AddModelError(string.Empty, localizer[outcome switch
        {
            SignInOutcome.LockedOut => "This account is temporarily locked. Please try again later.",
            SignInOutcome.Inactive => "This account has been deactivated.",
            _ => "Invalid user name or password.",
        }]);
        return Page();
    }

    private string SafeReturnUrl() => Url.IsLocalUrl(ReturnUrl) ? ReturnUrl! : "/";

    /// <summary>Validated with DataAnnotations; messages and display names are localized via the shared resources.</summary>
    public sealed class InputModel
    {
        [Required(ErrorMessage = "The {0} field is required.")]
        [Display(Name = "User name")]
        public string UserName { get; set; } = string.Empty;

        [Required(ErrorMessage = "The {0} field is required.")]
        [DataType(DataType.Password)]
        [Display(Name = "Password")]
        public string Password { get; set; } = string.Empty;

        [Display(Name = "Remember me")]
        public bool RememberMe { get; set; }
    }
}
