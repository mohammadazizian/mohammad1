using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Crm.Application.Features.Collaboration;
using Crm.Domain.Common;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Collab;

/// <summary>Endpoints of the contextual chat widget (HTML fragments + JSON for auto-complete).</summary>
public class ChatModel(IFileStorage files, ITrackableEntityResolver resolver) : AppPageModel
{
    /// <summary>The chat panel of an entity, loaded into the drawer.</summary>
    public async Task<IActionResult> OnGetAsync(string entity)
    {
        await DemandAsync(Permissions.Modules.Chat, Permissions.Actions.View);
        var thread = await Mediator.Send(new GetChatThreadQuery(Parse(entity)));
        var canPost = await CanAsync(Permissions.Modules.Chat, Permissions.Actions.Create);
        return Partial("_ChatPanelPartial", new ChatPanelViewModel(thread, canPost));
    }

    /// <summary>A single rendered message - requested by clients when SignalR announces it.</summary>
    public async Task<IActionResult> OnGetMessageAsync(Guid id)
    {
        await DemandAsync(Permissions.Modules.Chat, Permissions.Actions.View);
        return Partial("_ChatMessagePartial", await Mediator.Send(new GetChatMessageQuery(id)));
    }

    public async Task<IActionResult> OnPostAsync(string entity, string? body, Guid? parentId)
    {
        await DemandAsync(Permissions.Modules.Chat, Permissions.Actions.Create);

        var attachments = new List<StoredFile>();
        foreach (var file in Request.Form.Files.Where(f => f.Length > 0))
        {
            await using var stream = file.OpenReadStream();
            attachments.Add(await files.SaveAsync(stream, file.FileName, file.ContentType, HttpContext.RequestAborted));
        }

        var id = await Mediator.Send(new PostChatMessageCommand(Parse(entity), body, parentId, attachments));
        return new JsonResult(new { id, parentId });
    }

    /// <summary>Auto-complete for <c>@user</c>.</summary>
    public async Task<IActionResult> OnGetMentionsAsync(string? q)
    {
        await DemandAsync(Permissions.Modules.Chat, Permissions.Actions.View);
        var users = await Mediator.Send(new SearchMentionablesQuery(q));
        return new JsonResult(users.Select(u => new { value = u.Value, label = u.Label }));
    }

    /// <summary>Auto-complete for <c>#object</c>: searches every trackable entity type the user may view.</summary>
    public async Task<IActionResult> OnGetObjectsAsync(string? q)
    {
        await DemandAsync(Permissions.Modules.Chat, Permissions.Actions.View);

        var results = new List<object>();
        foreach (var item in await resolver.SearchAsync(q, take: 6, cancellationToken: HttpContext.RequestAborted))
        {
            if (await CanAsync(EntityRoutes.Module(item.Type), Permissions.Actions.View))
            {
                results.Add(new { type = item.Type.ToString(), id = item.Id, label = item.DisplayName, typeLabel = L.Enum(item.Type), icon = EntityRoutes.Icon(item.Type) });
            }
        }

        return new JsonResult(results);
    }

    private static EntityRef Parse(string entity) =>
        EntityRef.TryParse(entity, out var reference) ? reference : throw new BadHttpRequestException("Invalid entity reference.");
}
