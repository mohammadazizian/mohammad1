namespace Crm.Application.Common.Interfaces;

public sealed record UserSummary(Guid Id, string UserName, string FullName, string? Email, bool IsActive, IReadOnlyList<string> Roles);

public sealed record RoleSummary(Guid Id, string Name, string? Description, int UserCount, bool IsSystem);

public sealed record SaveUserRequest(
    Guid? Id,
    string UserName,
    string FullName,
    string? Email,
    string? Password,
    bool IsActive,
    IReadOnlyCollection<string> Roles);

/// <summary>Outcome of an identity operation; error messages come from ASP.NET Core Identity.</summary>
public sealed record IdentityResultDto(bool Succeeded, IReadOnlyList<string> Errors)
{
    public static IdentityResultDto Success { get; } = new(true, []);

    public static IdentityResultDto Failure(IEnumerable<string> errors) => new(false, errors.ToList());
}

/// <summary>Identity &amp; access management port (users, roles and their permissions).</summary>
public interface IIdentityService
{
    Task<IReadOnlyList<UserSummary>> GetUsersAsync(string? search = null, int take = 200, CancellationToken cancellationToken = default);
    Task<UserSummary?> GetUserAsync(Guid id, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<UserSummary>> FindByUserNamesAsync(IEnumerable<string> userNames, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<Guid>> GetUserIdsInRoleAsync(string roleName, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<Guid>> GetUserIdsWithPermissionAsync(string permission, CancellationToken cancellationToken = default);
    Task<IdentityResultDto> SaveUserAsync(SaveUserRequest request, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<RoleSummary>> GetRolesAsync(CancellationToken cancellationToken = default);
    Task<RoleSummary?> GetRoleAsync(Guid id, CancellationToken cancellationToken = default);
    Task<IdentityResultDto> CreateRoleAsync(string name, string? description, CancellationToken cancellationToken = default);
    Task<IdentityResultDto> DeleteRoleAsync(Guid id, CancellationToken cancellationToken = default);
    Task<IReadOnlySet<string>> GetRolePermissionsAsync(Guid roleId, CancellationToken cancellationToken = default);
    Task SetRolePermissionsAsync(Guid roleId, IEnumerable<string> permissions, CancellationToken cancellationToken = default);
}

/// <summary>Cached permission lookups used by the dynamic authorization policies.</summary>
public interface IPermissionService
{
    Task<bool> HasPermissionAsync(IEnumerable<string> roles, string permission, CancellationToken cancellationToken = default);
    Task<IReadOnlySet<string>> GetPermissionsAsync(string roleName, CancellationToken cancellationToken = default);
    void Invalidate(string roleName);
}

public enum SignInOutcome
{
    Succeeded,
    InvalidCredentials,
    LockedOut,
    Inactive,
}

/// <summary>Interactive sign-in / sign-out of the web user.</summary>
public interface ISignInService
{
    Task<SignInOutcome> PasswordSignInAsync(string userName, string password, bool rememberMe);
    Task SignOutAsync();
}
