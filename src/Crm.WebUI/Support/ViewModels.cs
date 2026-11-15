using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Models;
using Crm.Application.Features.Collaboration;
using Crm.Application.Features.Forms;
using Crm.Domain.Collaboration;
using Crm.Domain.Forms;
using Microsoft.AspNetCore.WebUtilities;

namespace Crm.WebUI.Support;

/// <summary>Model of the shared pager partial.</summary>
public sealed record PagerViewModel(int Page, int TotalPages, int TotalCount, Func<int, string> Url, string Target = "#list")
{
    // Keys that belong to a single action (htmx posts) and must not leak into paging links.
    private static readonly HashSet<string> TransientKeys = new(StringComparer.OrdinalIgnoreCase) { "p", "handler", "id", "status" };

    /// <summary>Builds a pager that keeps the current filters and only changes the page number.</summary>
    public static PagerViewModel For<T>(PagedList<T> list, HttpRequest request, string target = "#list")
    {
        var query = request.Query
            .Where(q => !TransientKeys.Contains(q.Key) && !string.IsNullOrEmpty(q.Value))
            .ToDictionary(q => q.Key, q => (string?)q.Value.ToString());

        return new PagerViewModel(
            list.Page,
            list.TotalPages,
            list.TotalCount,
            page => QueryHelpers.AddQueryString(request.Path, new Dictionary<string, string?>(query) { ["p"] = page.ToString() }),
            target);
    }
}

public sealed record ChatPanelViewModel(ChatThreadDto Thread, bool CanPost);

public sealed record TaskWidgetViewModel(
    TrackableInfo Entity,
    IReadOnlyList<TaskDto> Tasks,
    IReadOnlyList<ReminderDto> Reminders,
    IReadOnlyList<OptionDto> Users,
    IReadOnlyList<OptionDto> Roles,
    bool CanCreate,
    bool CanEdit,
    bool CanDelete);

/// <summary>Model of <c>_TaskFormFieldsPartial</c> (shared by the drawer widget and the Tasks page).</summary>
public sealed record TaskFormViewModel(IReadOnlyList<OptionDto> Users, IReadOnlyList<OptionDto> Roles, string IdPrefix);

/// <summary>Model of <c>_DynamicFormRendererPartial</c>.</summary>
public sealed record DynamicFormViewModel(
    FormDto Form,
    IReadOnlyDictionary<string, string?> Values,
    IReadOnlyDictionary<string, string> Errors,
    IReadOnlyDictionary<string, IReadOnlyList<OptionDto>> LookupOptions,
    IReadOnlyDictionary<string, FormFieldValue> ExistingFiles)
{
    public const string FieldPrefix = "f_";

    public static string InputName(FormField field) => FieldPrefix + field.Key;
}

public static class StatusStyles
{
    public static string For(TaskPriority priority) => priority switch
    {
        TaskPriority.Urgent => "pill-danger",
        TaskPriority.High => "pill-warning",
        TaskPriority.Low => string.Empty,
        _ => "pill-primary",
    };

    public static string For(TaskItemStatus status) => status switch
    {
        TaskItemStatus.Done => "pill-success",
        TaskItemStatus.InProgress => "pill-primary",
        TaskItemStatus.Cancelled => string.Empty,
        _ => "pill-warning",
    };

    public static string Icon(ActivityAction action) => action switch
    {
        ActivityAction.Created => "bi-plus-lg",
        ActivityAction.Updated => "bi-pencil",
        ActivityAction.Deleted => "bi-trash",
        ActivityAction.Commented => "bi-chat-left-text",
        ActivityAction.TaskCreated => "bi-check2-square",
        ActivityAction.TaskCompleted => "bi-check2-all",
        ActivityAction.ReminderSet => "bi-alarm",
        ActivityAction.StageChanged => "bi-signpost-split",
        ActivityAction.Converted => "bi-arrow-repeat",
        _ => "bi-dot",
    };

    public static string Icon(NotificationType type) => type switch
    {
        NotificationType.Mention => "bi-at",
        NotificationType.TaskAssigned => "bi-check2-square",
        NotificationType.Reminder => "bi-alarm",
        NotificationType.LowStock => "bi-exclamation-triangle",
        _ => "bi-bell",
    };
}

/// <summary>Model of <c>_KpiCardPartial</c>; <see cref="Label"/> is a resource key.</summary>
public sealed record KpiCard(string Label, string Value, string Hint, string Icon, string Url, bool Alert = false);
