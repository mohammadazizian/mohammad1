using Crm.Application.Common.Exceptions;
using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Collaboration;
using Crm.Domain.Collaboration;
using Crm.Domain.Common;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Collab;

/// <summary>Endpoints of the task &amp; reminder widget; each returns the refreshed widget fragment.</summary>
public class TasksModel(ITrackableEntityResolver resolver, IIdentityService identity) : AppPageModel
{
    private const string Module = Permissions.Modules.Tasks;

    public async Task<IActionResult> OnGetAsync(string entity)
    {
        await DemandAsync(Module, Permissions.Actions.View);
        return await WidgetAsync(Parse(entity));
    }

    public async Task<IActionResult> OnPostCreateAsync(string entity, [FromForm] TaskInput input)
    {
        await DemandAsync(Module, Permissions.Actions.Create);
        var reference = Parse(entity);
        await Mediator.Send(input.ToCommand(Formatter, reference));
        return await WidgetAsync(reference, L["Task created."]);
    }

    public async Task<IActionResult> OnPostStatusAsync(string entity, Guid id, TaskItemStatus status)
    {
        await DemandAsync(Module, Permissions.Actions.Edit);
        await Mediator.Send(new ChangeTaskStatusCommand(id, status));
        return await WidgetAsync(Parse(entity));
    }

    public async Task<IActionResult> OnPostDeleteAsync(string entity, Guid id)
    {
        await DemandAsync(Module, Permissions.Actions.Delete);
        await Mediator.Send(new DeleteTaskCommand(id));
        return await WidgetAsync(Parse(entity));
    }

    public async Task<IActionResult> OnPostReminderAsync(string entity, string message, DateTime remindAt)
    {
        await DemandAsync(Module, Permissions.Actions.View);
        var reference = Parse(entity);
        await Mediator.Send(new CreateReminderCommand { Entity = reference, Message = message, RemindAt = Formatter.ToUtc(remindAt) });
        return await WidgetAsync(reference, L["Reminder set."]);
    }

    public async Task<IActionResult> OnPostDeleteReminderAsync(string entity, Guid id)
    {
        await DemandAsync(Module, Permissions.Actions.View);
        await Mediator.Send(new DeleteReminderCommand(id));
        return await WidgetAsync(Parse(entity));
    }

    private async Task<IActionResult> WidgetAsync(EntityRef entity, string? toast = null)
    {
        var info = await resolver.ResolveAsync(entity, HttpContext.RequestAborted)
            ?? throw new NotFoundException(entity.Type.ToString(), entity.Id);
        var tasks = await Mediator.Send(new GetTasksQuery { Entity = entity, PageSize = 100 });
        var reminders = await Mediator.Send(new GetRemindersQuery(entity));
        var (users, roles) = await TaskInput.LoadAssigneesAsync(identity, HttpContext.RequestAborted);

        if (toast is not null)
        {
            HxToast(toast);
        }

        return Partial("_TaskWidgetPartial", new TaskWidgetViewModel(
            info, tasks.Items, reminders, users, roles,
            CanCreate: await CanAsync(Module, Permissions.Actions.Create),
            CanEdit: await CanAsync(Module, Permissions.Actions.Edit),
            CanDelete: await CanAsync(Module, Permissions.Actions.Delete)));
    }

    private static EntityRef Parse(string entity) =>
        EntityRef.TryParse(entity, out var reference) ? reference : throw new BadHttpRequestException("Invalid entity reference.");
}

/// <summary>Posted task form (see <c>_TaskFormFieldsPartial</c>); date-times are in the business time zone.</summary>
public sealed class TaskInput
{
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
    public TaskPriority Priority { get; set; } = TaskPriority.Normal;
    public DateTime? DueAt { get; set; }
    public DateTime? RemindAt { get; set; }
    public Guid? AssignedToUserId { get; set; }
    public string? AssignedToRole { get; set; }

    public CreateTaskCommand ToCommand(ILocalizedFormatter formatter, EntityRef? entity = null) => new()
    {
        Title = Title ?? string.Empty,
        Description = Description,
        Priority = Priority,
        DueAt = DueAt is { } due ? formatter.ToUtc(due) : null,
        RemindAt = RemindAt is { } remind ? formatter.ToUtc(remind) : null,
        AssignedToUserId = AssignedToUserId,
        AssignedToRole = AssignedToRole,
        Entity = entity,
    };

    public static async Task<(IReadOnlyList<OptionDto> Users, IReadOnlyList<OptionDto> Roles)> LoadAssigneesAsync(
        IIdentityService identity, CancellationToken cancellationToken)
    {
        var users = await identity.GetUsersAsync(cancellationToken: cancellationToken);
        var roles = await identity.GetRolesAsync(cancellationToken);
        return (
            users.Where(u => u.IsActive).Select(u => new OptionDto(u.Id.ToString(), u.FullName)).ToList(),
            roles.Select(r => new OptionDto(r.Name, r.Name)).ToList());
    }
}
