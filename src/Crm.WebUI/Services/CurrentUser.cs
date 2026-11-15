using System.Security.Claims;
using Crm.Application.Common.Interfaces;
using Crm.Infrastructure.Identity;

namespace Crm.WebUI.Services;

/// <summary>Reads the signed-in user from the current HTTP request (works for SignalR hubs as well).</summary>
public sealed class CurrentUser(IHttpContextAccessor accessor) : ICurrentUser
{
    private ClaimsPrincipal? Principal => accessor.HttpContext?.User;

    public Guid? UserId => Guid.TryParse(Principal?.FindFirstValue(ClaimTypes.NameIdentifier), out var id) ? id : null;

    public string? UserName => Principal?.Identity?.Name;

    public string? DisplayName => Principal?.FindFirstValue(AppClaimsPrincipalFactory.FullNameClaim) ?? UserName;

    public bool IsAuthenticated => Principal?.Identity?.IsAuthenticated == true;

    public IReadOnlyCollection<string> Roles => Principal?.FindAll(ClaimTypes.Role).Select(c => c.Value).ToList() ?? [];
}
