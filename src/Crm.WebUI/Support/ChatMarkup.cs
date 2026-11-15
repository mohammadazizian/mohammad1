using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using Crm.Domain.Common;
using Microsoft.AspNetCore.Html;

namespace Crm.WebUI.Support;

/// <summary>
/// Renders the chat mini-markup to safe HTML: everything is HTML-encoded, then
/// <c>@user</c> becomes a mention chip and <c>#[Type:Guid|Label]</c> a link to the object.
/// </summary>
public static partial class ChatMarkup
{
    public static IHtmlContent Render(string? body)
    {
        if (string.IsNullOrEmpty(body))
        {
            return HtmlString.Empty;
        }

        var html = new StringBuilder(body.Length + 64);
        var position = 0;

        foreach (Match match in Token().Matches(body))
        {
            html.Append(Encode(body[position..match.Index]));
            position = match.Index + match.Length;

            if (match.Groups["user"].Success)
            {
                html.Append("<span class=\"mention\">@").Append(Encode(match.Groups["user"].Value)).Append("</span>");
            }
            else if (EntityRef.TryParse($"{match.Groups["type"].Value}:{match.Groups["id"].Value}", out var entity))
            {
                html.Append("<a class=\"object-link\" href=\"").Append(EntityRoutes.Url(entity)).Append("\">")
                    .Append("<i class=\"bi ").Append(EntityRoutes.Icon(entity.Type)).Append("\"></i> ")
                    .Append(Encode(match.Groups["label"].Value)).Append("</a>");
            }
            else
            {
                html.Append(Encode(match.Value));
            }
        }

        html.Append(Encode(body[position..]));
        return new HtmlString(html.ToString());
    }

    private static string Encode(string text) => WebUtility.HtmlEncode(text).Replace("\n", "<br>");

    [GeneratedRegex(@"#\[(?<type>\w+):(?<id>[0-9a-fA-F-]{36})\|(?<label>[^\]]{1,200})\]|(?<![\w@])@(?<user>[A-Za-z0-9._-]{2,64})")]
    private static partial Regex Token();
}
