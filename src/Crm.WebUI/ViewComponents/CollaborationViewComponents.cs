using Crm.Application.Common.Security;
using Crm.Application.Features.Collaboration;
using Crm.Domain.Common;
using MediatR;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.ViewComponents;

public sealed record EntityCollaborationViewModel(EntityRef Entity, CollaborationSummaryDto Summary, bool CanChat, bool CanSeeTasks);

/// <summary>
/// Drop-in collaboration toolbar for any trackable entity page. Its buttons open the chat and
/// the task / reminder widgets in the slide-over drawer:
/// <c>&lt;vc:entity-collaboration type="Customer" id="@Model.Id" /&gt;</c>.
/// </summary>
public sealed class EntityCollaborationViewComponent(ISender mediator, IAuthorizationService authorization) : ViewComponent
{
    public async Task<IViewComponentResult> InvokeAsync(TrackableEntityType type, Guid id)
    {
        var entity = new EntityRef(type, id);
        var canChat = await CanAsync(Permissions.Modules.Chat);
        var canSeeTasks = await CanAsync(Permissions.Modules.Tasks);
        var summary = canChat || canSeeTasks
            ? await mediator.Send(new GetCollaborationSummaryQuery(entity))
            : new CollaborationSummaryDto(0, 0);

        return View(new EntityCollaborationViewModel(entity, summary, canChat, canSeeTasks));
    }

    private async Task<bool> CanAsync(string module) =>
        (await authorization.AuthorizeAsync(UserClaimsPrincipal, Permissions.PolicyPrefix + Permissions.For(module, Permissions.Actions.View))).Succeeded;
}

/// <summary>Activity timeline of an entity: <c>&lt;vc:activity-timeline type="Customer" id="@Model.Id" /&gt;</c>.</summary>
public sealed class ActivityTimelineViewComponent(ISender mediator) : ViewComponent
{
    public async Task<IViewComponentResult> InvokeAsync(TrackableEntityType type, Guid id, int take = 15) =>
        View(await mediator.Send(new GetActivityQuery(new EntityRef(type, id), take)));
}

/// <summary>Navbar bell with the unread-notification badge.</summary>
public sealed class NotificationBellViewComponent(ISender mediator) : ViewComponent
{
    public async Task<IViewComponentResult> InvokeAsync() =>
        View((await mediator.Send(new GetNotificationsQuery(Take: 1))).UnreadCount);
}
