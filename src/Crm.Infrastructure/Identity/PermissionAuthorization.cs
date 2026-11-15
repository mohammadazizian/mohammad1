using System.Security.Claims;
using Crm.Application.Common.Security;
using Crm.Infrastructure.Persistence;
using Microsoft.AspNetCore.Authorization;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Options;

namespace Crm.Infrastructure.Identity;

/// <summary>
/// Role → permissions lookups, cached in memory. The cache entry of a role is dropped
/// whenever its permissions are edited, so changes apply at runtime without a re-login.
/// </summary>
public sealed class PermissionService(ApplicationDbContext db, IMemoryCache cache) : IPermissionService
{
    private static readonly TimeSpan CacheDuration = TimeSpan.FromMinutes(10);

    public async Task<bool> HasPermissionAsync(IEnumerable<string> roles, string permission, CancellationToken cancellationToken = default)
    {
        foreach (var role in roles)
        {
            if (role == Permissions.AdministratorRole || (await GetPermissionsAsync(role, cancellationToken)).Contains(permission))
            {
                return true;
            }
        }

        return false;
    }

    public async Task<IReadOnlySet<string>> GetPermissionsAsync(string roleName, CancellationToken cancellationToken = default) =>
        (await cache.GetOrCreateAsync(CacheKey(roleName), async entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = CacheDuration;
            var normalized = roleName.ToUpperInvariant();
            var permissions = await (
                from claim in db.RoleClaims.AsNoTracking()
                join role in db.Roles.AsNoTracking() on claim.RoleId equals role.Id
                where role.NormalizedName == normalized && claim.ClaimType == Permissions.ClaimType
                select claim.ClaimValue!).ToListAsync(cancellationToken);
            return (IReadOnlySet<string>)permissions.ToHashSet(StringComparer.OrdinalIgnoreCase);
        }))!;

    public void Invalidate(string roleName) => cache.Remove(CacheKey(roleName));

    private static string CacheKey(string roleName) => $"permissions:{roleName.ToUpperInvariant()}";
}

public sealed record PermissionRequirement(string Permission) : IAuthorizationRequirement;

/// <summary>
/// Declarative permission check, e.g. <c>[HasPermission(Modules.Customers, Actions.View)]</c>.
/// Resolved by <see cref="PermissionPolicyProvider"/> - no policy registration needed.
/// </summary>
[AttributeUsage(AttributeTargets.Class | AttributeTargets.Method, AllowMultiple = true)]
public sealed class HasPermissionAttribute : AuthorizeAttribute
{
    public HasPermissionAttribute(string module, string action)
        : base(Permissions.PolicyPrefix + Permissions.For(module, action))
    {
    }
}

/// <summary>Creates a policy on the fly for every "Permission:{name}" policy name.</summary>
public sealed class PermissionPolicyProvider(IOptions<AuthorizationOptions> options) : DefaultAuthorizationPolicyProvider(options)
{
    public override async Task<AuthorizationPolicy?> GetPolicyAsync(string policyName)
    {
        if (!policyName.StartsWith(Permissions.PolicyPrefix, StringComparison.Ordinal))
        {
            return await base.GetPolicyAsync(policyName);
        }

        return new AuthorizationPolicyBuilder()
            .RequireAuthenticatedUser()
            .AddRequirements(new PermissionRequirement(policyName[Permissions.PolicyPrefix.Length..]))
            .Build();
    }
}

public sealed class PermissionAuthorizationHandler(IPermissionService permissions) : AuthorizationHandler<PermissionRequirement>
{
    protected override async Task HandleRequirementAsync(AuthorizationHandlerContext context, PermissionRequirement requirement)
    {
        var roles = context.User.FindAll(ClaimTypes.Role).Select(c => c.Value);
        if (await permissions.HasPermissionAsync(roles, requirement.Permission))
        {
            context.Succeed(requirement);
        }
    }
}
