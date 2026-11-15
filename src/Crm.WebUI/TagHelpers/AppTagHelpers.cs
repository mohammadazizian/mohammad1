using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Security;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.Rendering;
using Microsoft.AspNetCore.Mvc.TagHelpers;
using Microsoft.AspNetCore.Mvc.ViewFeatures;
using Microsoft.AspNetCore.Razor.TagHelpers;

namespace Crm.WebUI.TagHelpers;

/// <summary>
/// Renders the element only when the user holds the permission:
/// <c>&lt;a asp-permission="Customers.Create"&gt;…&lt;/a&gt;</c>.
/// </summary>
[HtmlTargetElement(Attributes = AttributeName)]
public sealed class PermissionTagHelper(IAuthorizationService authorization) : TagHelper
{
    private const string AttributeName = "asp-permission";

    [HtmlAttributeName(AttributeName)]
    public string Permission { get; set; } = string.Empty;

    [ViewContext]
    [HtmlAttributeNotBound]
    public ViewContext ViewContext { get; set; } = default!;

    public override async Task ProcessAsync(TagHelperContext context, TagHelperOutput output)
    {
        var result = await authorization.AuthorizeAsync(ViewContext.HttpContext.User, Permissions.PolicyPrefix + Permission);
        if (!result.Succeeded)
        {
            output.SuppressOutput();
        }
    }
}

public enum TimeDisplayMode
{
    Date,
    DateTime,
    Relative,
}

/// <summary>
/// Culture-aware date output (Jalali for fa-IR, Gregorian otherwise):
/// <c>&lt;time-display value="@item.CreatedAt" mode="Relative" /&gt;</c>.
/// </summary>
[HtmlTargetElement("time-display", TagStructure = TagStructure.WithoutEndTag)]
public sealed class TimeDisplayTagHelper(ILocalizedFormatter formatter) : TagHelper
{
    public DateTime? Value { get; set; }

    public TimeDisplayMode Mode { get; set; } = TimeDisplayMode.Date;

    public override void Process(TagHelperContext context, TagHelperOutput output)
    {
        output.TagName = "time";
        output.TagMode = TagMode.StartTagAndEndTag;

        if (Value is not { } value)
        {
            output.Content.SetContent("—");
            return;
        }

        output.Attributes.SetAttribute("datetime", value.ToString("yyyy-MM-ddTHH:mm:ssZ"));
        output.Attributes.SetAttribute("title", formatter.DateTime(value));
        output.Content.SetContent(Mode switch
        {
            TimeDisplayMode.DateTime => formatter.DateTime(value),
            TimeDisplayMode.Relative => formatter.RelativeTime(value),
            _ => formatter.Date(value),
        });
    }
}

/// <summary>
/// Marks a navigation link as active when the current page lives under its path:
/// <c>&lt;a href="/Customers" nav-active="/Customers"&gt;</c>.
/// </summary>
[HtmlTargetElement("a", Attributes = AttributeName)]
public sealed class NavActiveTagHelper : TagHelper
{
    private const string AttributeName = "nav-active";

    [HtmlAttributeName(AttributeName)]
    public string Prefix { get; set; } = string.Empty;

    [ViewContext]
    [HtmlAttributeNotBound]
    public ViewContext ViewContext { get; set; } = default!;

    public override void Process(TagHelperContext context, TagHelperOutput output)
    {
        var path = ViewContext.HttpContext.Request.Path.Value ?? "/";
        var isActive = Prefix == "/"
            ? path is "/" or "/Index"
            : path.StartsWith(Prefix, StringComparison.OrdinalIgnoreCase);

        if (isActive)
        {
            output.AddClass("active", System.Text.Encodings.Web.HtmlEncoder.Default);
            output.Attributes.SetAttribute("aria-current", "page");
        }
    }
}
