using System.Text.RegularExpressions;
using Crm.Application.Common.Security;
using Crm.Domain.Common;
using Microsoft.Extensions.Localization;

namespace Crm.WebUI.Support;

public static partial class TextHelpers
{
    /// <summary>"LowStockThreshold" → "Low stock threshold".</summary>
    public static string Humanize(string pascalCase)
    {
        var words = WordBoundary().Replace(pascalCase, " ");
        var text = words.Length == 0 ? words : char.ToUpperInvariant(words[0]) + words[1..].ToLowerInvariant();
        return Acronyms.GetValueOrDefault(text, text);
    }

    private static readonly Dictionary<string, string> Acronyms = new() { ["Sku"] = "SKU", ["Tax id"] = "Tax ID" };

    [GeneratedRegex("(?<=[a-z0-9])(?=[A-Z])")]
    private static partial Regex WordBoundary();
}

public static class LocalizerExtensions
{
    /// <summary>Localized name of an enum member, looked up as "{EnumType}_{Member}".</summary>
    public static string Enum<TEnum>(this IStringLocalizer<SharedResource> localizer, TEnum value)
        where TEnum : struct, Enum => localizer.EnumName(typeof(TEnum), value.ToString());

    public static string EnumName(this IStringLocalizer<SharedResource> localizer, Type enumType, string member)
    {
        var text = localizer[$"{enumType.Name}_{member}"];
        return text.ResourceNotFound ? TextHelpers.Humanize(member) : text.Value;
    }

    /// <summary>Localized caption of a property / column name such as "UnitPrice".</summary>
    public static string Field(this IStringLocalizer<SharedResource> localizer, string name) =>
        localizer[TextHelpers.Humanize(name)];
}

/// <summary>Maps trackable entities to their detail pages - the UI side of the polymorphic engine.</summary>
public static class EntityRoutes
{
    public static string Url(TrackableEntityType type, Guid id) => type switch
    {
        TrackableEntityType.Customer => $"/Customers/Details/{id}",
        TrackableEntityType.Product => $"/Products/Details/{id}",
        TrackableEntityType.InventoryTransaction => $"/Inventory/Details/{id}",
        TrackableEntityType.FormSubmission => $"/Forms/Submission/{id}",
        TrackableEntityType.Lead => $"/Leads/Details/{id}",
        TrackableEntityType.Deal => $"/Deals/Details/{id}",
        _ => "/",
    };

    public static string Url(EntityRef entity) => Url(entity.Type, entity.Id);

    public static string Icon(TrackableEntityType type) => type switch
    {
        TrackableEntityType.Customer => "bi-building",
        TrackableEntityType.Product => "bi-box-seam",
        TrackableEntityType.InventoryTransaction => "bi-arrow-left-right",
        TrackableEntityType.FormSubmission => "bi-ui-checks",
        TrackableEntityType.Lead => "bi-person-plus",
        TrackableEntityType.Deal => "bi-briefcase",
        _ => "bi-link-45deg",
    };

    /// <summary>The permission module that guards viewing an entity type.</summary>
    public static string Module(TrackableEntityType type) => type switch
    {
        TrackableEntityType.Customer => Permissions.Modules.Customers,
        TrackableEntityType.Product => Permissions.Modules.Products,
        TrackableEntityType.InventoryTransaction => Permissions.Modules.Inventory,
        TrackableEntityType.FormSubmission => Permissions.Modules.Forms,
        TrackableEntityType.Lead => Permissions.Modules.Leads,
        TrackableEntityType.Deal => Permissions.Modules.Deals,
        _ => Permissions.Modules.Dashboard,
    };
}
