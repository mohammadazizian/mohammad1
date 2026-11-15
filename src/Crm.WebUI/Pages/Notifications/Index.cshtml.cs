using Crm.Application.Features.Collaboration;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Notifications;

public class IndexModel : AppPageModel
{
    public NotificationListDto Notifications { get; private set; } = new([], 0);

    public async Task OnGetAsync() => Notifications = await Mediator.Send(new GetNotificationsQuery(Take: 100));

    /// <summary>Content of the navbar bell dropdown (htmx).</summary>
    public async Task<IActionResult> OnGetDropdownAsync() =>
        Partial("_NotificationDropdownPartial", await Mediator.Send(new GetNotificationsQuery(Take: 8)));

    /// <summary>Marks one (or, without id, all) notifications as read and returns the refreshed fragment.</summary>
    public async Task<IActionResult> OnPostReadAsync(Guid? id, bool dropdown)
    {
        await Mediator.Send(new MarkNotificationsReadCommand(id));
        if (dropdown)
        {
            return await OnGetDropdownAsync();
        }

        return IsHtmx
            ? Partial("_NotificationListPartial", await Mediator.Send(new GetNotificationsQuery(Take: 100)))
            : RedirectToPage();
    }

    /// <summary>Opens the object behind a notification and marks it as read.</summary>
    public async Task<IActionResult> OnGetOpenAsync(Guid id, string? target)
    {
        await Mediator.Send(new MarkNotificationsReadCommand(id));
        return LocalRedirect(Url.IsLocalUrl(target) ? target : "/Tasks");
    }
}
