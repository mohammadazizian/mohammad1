using System.Security.Claims;
using Crm.Application.Common.Security;
using Crm.Infrastructure.Persistence;
using Microsoft.AspNetCore.Identity;

namespace Crm.Infrastructure.Identity;

public sealed class IdentityService(
    UserManager<ApplicationUser> userManager,
    RoleManager<ApplicationRole> roleManager,
    ApplicationDbContext db,
    IPermissionService permissionService)
    : IIdentityService
{
    public async Task<IReadOnlyList<UserSummary>> GetUsersAsync(string? search = null, int take = 200, CancellationToken cancellationToken = default)
    {
        var query = db.Users.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(search))
        {
            var term = search.Trim();
            query = query.Where(u => u.UserName!.Contains(term) || u.FullName.Contains(term) || u.Email!.Contains(term));
        }

        var users = await query.OrderBy(u => u.FullName).Take(take).ToListAsync(cancellationToken);
        return await ToSummariesAsync(users, cancellationToken);
    }

    public async Task<UserSummary?> GetUserAsync(Guid id, CancellationToken cancellationToken = default)
    {
        var user = await db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Id == id, cancellationToken);
        return user is null ? null : (await ToSummariesAsync([user], cancellationToken))[0];
    }

    public async Task<IReadOnlyList<UserSummary>> FindByUserNamesAsync(IEnumerable<string> userNames, CancellationToken cancellationToken = default)
    {
        var normalized = userNames.Select(n => n.ToUpperInvariant()).Distinct().ToList();
        if (normalized.Count == 0)
        {
            return [];
        }

        var users = await db.Users.AsNoTracking()
            .Where(u => u.IsActive && normalized.Contains(u.NormalizedUserName!))
            .ToListAsync(cancellationToken);
        return await ToSummariesAsync(users, cancellationToken);
    }

    public async Task<IReadOnlyList<Guid>> GetUserIdsInRoleAsync(string roleName, CancellationToken cancellationToken = default)
    {
        var normalized = roleName.ToUpperInvariant();
        return await (
            from userRole in db.UserRoles
            join role in db.Roles on userRole.RoleId equals role.Id
            join user in db.Users on userRole.UserId equals user.Id
            where role.NormalizedName == normalized && user.IsActive
            select user.Id).Distinct().ToListAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<Guid>> GetUserIdsWithPermissionAsync(string permission, CancellationToken cancellationToken = default)
    {
        var roleIds = db.Roles
            .Where(r => r.Name == Permissions.AdministratorRole
                        || db.RoleClaims.Any(c => c.RoleId == r.Id && c.ClaimType == Permissions.ClaimType && c.ClaimValue == permission))
            .Select(r => r.Id);

        return await (
            from userRole in db.UserRoles
            join user in db.Users on userRole.UserId equals user.Id
            where roleIds.Contains(userRole.RoleId) && user.IsActive
            select user.Id).Distinct().ToListAsync(cancellationToken);
    }

    public async Task<IdentityResultDto> SaveUserAsync(SaveUserRequest request, CancellationToken cancellationToken = default)
    {
        ApplicationUser? user;
        IdentityResult result;

        if (request.Id is { } id)
        {
            user = await userManager.FindByIdAsync(id.ToString());
            if (user is null)
            {
                return IdentityResultDto.Failure(["User not found."]);
            }

            user.UserName = request.UserName.Trim();
            user.FullName = request.FullName.Trim();
            user.Email = request.Email?.Trim();
            user.IsActive = request.IsActive;
            result = await userManager.UpdateAsync(user);

            if (result.Succeeded && !string.IsNullOrEmpty(request.Password))
            {
                var token = await userManager.GeneratePasswordResetTokenAsync(user);
                result = await userManager.ResetPasswordAsync(user, token, request.Password);
            }
        }
        else
        {
            user = new ApplicationUser
            {
                Id = Guid.CreateVersion7(),
                UserName = request.UserName.Trim(),
                FullName = request.FullName.Trim(),
                Email = request.Email?.Trim(),
                IsActive = request.IsActive,
                EmailConfirmed = true,
            };
            result = await userManager.CreateAsync(user, request.Password ?? string.Empty);
        }

        if (!result.Succeeded)
        {
            return ToDto(result);
        }

        var currentRoles = await userManager.GetRolesAsync(user);
        var toRemove = currentRoles.Except(request.Roles, StringComparer.OrdinalIgnoreCase).ToList();
        var toAdd = request.Roles.Except(currentRoles, StringComparer.OrdinalIgnoreCase).ToList();

        if (toRemove.Count != 0)
        {
            result = await userManager.RemoveFromRolesAsync(user, toRemove);
        }

        if (result.Succeeded && toAdd.Count != 0)
        {
            result = await userManager.AddToRolesAsync(user, toAdd);
        }

        // Force other sessions of the user to pick up the new roles / state.
        await userManager.UpdateSecurityStampAsync(user);
        return ToDto(result);
    }

    public async Task<IReadOnlyList<RoleSummary>> GetRolesAsync(CancellationToken cancellationToken = default) =>
        await db.Roles.AsNoTracking()
            .OrderBy(r => r.Name)
            .Select(r => new RoleSummary(r.Id, r.Name!, r.Description, db.UserRoles.Count(ur => ur.RoleId == r.Id), r.IsSystem))
            .ToListAsync(cancellationToken);

    public async Task<RoleSummary?> GetRoleAsync(Guid id, CancellationToken cancellationToken = default) =>
        await db.Roles.AsNoTracking()
            .Where(r => r.Id == id)
            .Select(r => new RoleSummary(r.Id, r.Name!, r.Description, db.UserRoles.Count(ur => ur.RoleId == r.Id), r.IsSystem))
            .FirstOrDefaultAsync(cancellationToken);

    public async Task<IdentityResultDto> CreateRoleAsync(string name, string? description, CancellationToken cancellationToken = default) =>
        ToDto(await roleManager.CreateAsync(new ApplicationRole(name.Trim(), description) { Id = Guid.CreateVersion7() }));

    public async Task<IdentityResultDto> DeleteRoleAsync(Guid id, CancellationToken cancellationToken = default)
    {
        var role = await roleManager.FindByIdAsync(id.ToString());
        if (role is null)
        {
            return IdentityResultDto.Failure(["Role not found."]);
        }

        if (role.IsSystem)
        {
            return IdentityResultDto.Failure(["System roles cannot be deleted."]);
        }

        var result = await roleManager.DeleteAsync(role);
        permissionService.Invalidate(role.Name!);
        return ToDto(result);
    }

    public async Task<IReadOnlySet<string>> GetRolePermissionsAsync(Guid roleId, CancellationToken cancellationToken = default)
    {
        var permissions = await db.RoleClaims.AsNoTracking()
            .Where(c => c.RoleId == roleId && c.ClaimType == Permissions.ClaimType)
            .Select(c => c.ClaimValue!)
            .ToListAsync(cancellationToken);
        return permissions.ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    public async Task SetRolePermissionsAsync(Guid roleId, IEnumerable<string> permissions, CancellationToken cancellationToken = default)
    {
        var role = await roleManager.FindByIdAsync(roleId.ToString())
            ?? throw new Application.Common.Exceptions.NotFoundException("Role", roleId);

        var desired = permissions.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var current = (await roleManager.GetClaimsAsync(role)).Where(c => c.Type == Permissions.ClaimType).ToList();

        foreach (var claim in current.Where(c => !desired.Contains(c.Value)))
        {
            await roleManager.RemoveClaimAsync(role, claim);
        }

        foreach (var permission in desired.Except(current.Select(c => c.Value), StringComparer.OrdinalIgnoreCase))
        {
            await roleManager.AddClaimAsync(role, new Claim(Permissions.ClaimType, permission));
        }

        permissionService.Invalidate(role.Name!);
    }

    private async Task<IReadOnlyList<UserSummary>> ToSummariesAsync(List<ApplicationUser> users, CancellationToken cancellationToken)
    {
        var ids = users.Select(u => u.Id).ToList();
        var roles = await (
            from userRole in db.UserRoles
            join role in db.Roles on userRole.RoleId equals role.Id
            where ids.Contains(userRole.UserId)
            select new { userRole.UserId, role.Name }).ToListAsync(cancellationToken);
        var rolesByUser = roles.ToLookup(r => r.UserId, r => r.Name!);

        return users
            .Select(u => new UserSummary(u.Id, u.UserName!, u.FullName, u.Email, u.IsActive, rolesByUser[u.Id].Order().ToList()))
            .ToList();
    }

    private static IdentityResultDto ToDto(IdentityResult result) =>
        result.Succeeded ? IdentityResultDto.Success : IdentityResultDto.Failure(result.Errors.Select(e => e.Description));
}
