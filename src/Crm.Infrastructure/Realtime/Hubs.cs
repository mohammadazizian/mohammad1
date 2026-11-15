using System.Security.Claims;
using Crm.Application.Features.Collaboration;
using Crm.Domain.Collaboration;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace Crm.Infrastructure.Realtime;

/// <summary>
/// Real-time channel of the contextual chat. Clients join one group per open entity
/// ("chat:{EntityType}:{EntityId}") and get a "messagePosted" event for each new message.
/// </summary>
[Authorize]
public sealed class ChatHub(IPermissionService permissions) : Hub
{
    public const string Route = "/hubs/chat";

    public static string GroupName(EntityRef entity) => $"chat:{entity.Type}:{entity.Id}";

    public async Task JoinEntity(string entityType, Guid entityId)
    {
        var entity = await AuthorizeAsync(entityType, entityId);
        await Groups.AddToGroupAsync(Context.ConnectionId, GroupName(entity));
    }

    public async Task LeaveEntity(string entityType, Guid entityId)
    {
        if (EntityRef.TryParse($"{entityType}:{entityId}", out var entity))
        {
            await Groups.RemoveFromGroupAsync(Context.ConnectionId, GroupName(entity));
        }
    }

    /// <summary>Broadcasts a "someone is typing" hint to the other viewers of the entity.</summary>
    public async Task Typing(string entityType, Guid entityId)
    {
        var entity = await AuthorizeAsync(entityType, entityId);
        var name = Context.User?.FindFirstValue(Identity.AppClaimsPrincipalFactory.FullNameClaim) ?? Context.User?.Identity?.Name;
        await Clients.OthersInGroup(GroupName(entity)).SendAsync("typing", new { entityType = entity.Type.ToString(), entityId, name });
    }

    private async Task<EntityRef> AuthorizeAsync(string entityType, Guid entityId)
    {
        if (!EntityRef.TryParse($"{entityType}:{entityId}", out var entity))
        {
            throw new HubException("Unknown entity.");
        }

        var roles = Context.User?.FindAll(ClaimTypes.Role).Select(c => c.Value) ?? [];
        if (!await permissions.HasPermissionAsync(roles, ChatPermissions.View))
        {
            throw new HubException("Access denied.");
        }

        return entity;
    }
}

/// <summary>Per-user channel for in-app notifications (mentions, task assignments, reminders, alerts).</summary>
[Authorize]
public sealed class NotificationHub : Hub
{
    public const string Route = "/hubs/notifications";
}

public sealed class SignalRRealtimeNotifier(IHubContext<ChatHub> chatHub, IHubContext<NotificationHub> notificationHub)
    : IRealtimeNotifier
{
    public Task ChatMessagePostedAsync(EntityRef entity, Guid messageId, Guid? parentMessageId, CancellationToken cancellationToken = default) =>
        chatHub.Clients.Group(ChatHub.GroupName(entity)).SendAsync(
            "messagePosted",
            new { entityType = entity.Type.ToString(), entityId = entity.Id, messageId, parentMessageId },
            cancellationToken);

    public Task NotificationCreatedAsync(Notification notification, CancellationToken cancellationToken = default) =>
        notificationHub.Clients.User(notification.UserId.ToString()).SendAsync(
            "notification",
            new
            {
                id = notification.Id,
                type = notification.Type.ToString(),
                message = notification.Message,
                entityType = notification.EntityType?.ToString(),
                entityId = notification.EntityId,
            },
            cancellationToken);
}
