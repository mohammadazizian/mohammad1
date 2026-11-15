using System.Security.Claims;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;

namespace Crm.Infrastructure.Identity;

public sealed class SignInService(SignInManager<ApplicationUser> signInManager, UserManager<ApplicationUser> userManager)
    : ISignInService
{
    public async Task<SignInOutcome> PasswordSignInAsync(string userName, string password, bool rememberMe)
    {
        var user = await userManager.FindByNameAsync(userName.Trim());
        if (user is null)
        {
            return SignInOutcome.InvalidCredentials;
        }

        if (!user.IsActive)
        {
            return SignInOutcome.Inactive;
        }

        var result = await signInManager.PasswordSignInAsync(user, password, rememberMe, lockoutOnFailure: true);
        return result switch
        {
            { Succeeded: true } => SignInOutcome.Succeeded,
            { IsLockedOut: true } => SignInOutcome.LockedOut,
            _ => SignInOutcome.InvalidCredentials,
        };
    }

    public Task SignOutAsync() => signInManager.SignOutAsync();
}

/// <summary>
/// Puts identity, display name and role names into the auth cookie. Permissions are deliberately
/// NOT stored as claims: they are resolved per request from the cached role → permission map,
/// which keeps the cookie small and lets permission changes apply immediately.
/// </summary>
public sealed class AppClaimsPrincipalFactory(UserManager<ApplicationUser> userManager, IOptions<IdentityOptions> options)
    : UserClaimsPrincipalFactory<ApplicationUser>(userManager, options)
{
    public const string FullNameClaim = "full_name";

    protected override async Task<ClaimsIdentity> GenerateClaimsAsync(ApplicationUser user)
    {
        var identity = await base.GenerateClaimsAsync(user);
        identity.AddClaim(new Claim(FullNameClaim, user.FullName));
        foreach (var role in await UserManager.GetRolesAsync(user))
        {
            identity.AddClaim(new Claim(Options.ClaimsIdentity.RoleClaimType, role));
        }

        return identity;
    }
}
