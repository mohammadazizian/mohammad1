using System.Text.Json;
using System.Text.Json.Serialization;
using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using Crm.Domain.Forms;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.FormBuilder;

/// <summary>Visual designer of a dynamic form; the field schema travels as JSON (see form-builder.js).</summary>
public class EditModel : AppPageModel
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter() },
    };

    [BindProperty]
    public UpsertFormCommand Input { get; set; } = new();

    /// <summary>The designed fields, serialized by the client.</summary>
    [BindProperty]
    public string FieldsJson { get; set; } = "[]";

    public bool IsNew => Input.Id is null;

    public async Task<IActionResult> OnGetAsync(Guid? id)
    {
        await DemandAsync(Permissions.Modules.Forms, id is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        if (id is not null)
        {
            var form = await Mediator.Send(new GetFormQuery(id));
            Input = new UpsertFormCommand
            {
                Id = form.Id, Code = form.Code, TitleEn = form.Title.En, TitleFa = form.Title.Fa,
                DescriptionEn = form.Description.En, DescriptionFa = form.Description.Fa, IsPublished = form.IsPublished,
            };
            FieldsJson = JsonSerializer.Serialize(form.Fields, JsonOptions);
        }

        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        await DemandAsync(Permissions.Modules.Forms, IsNew ? Permissions.Actions.Create : Permissions.Actions.Edit);

        try
        {
            Input.Fields = JsonSerializer.Deserialize<List<FormField>>(FieldsJson, JsonOptions) ?? [];
        }
        catch (JsonException)
        {
            ModelState.AddModelError(string.Empty, L["The form definition could not be read."]);
            return Page();
        }

        // Only the JSON payload describes the fields; ignore binder noise for the nested list.
        foreach (var key in ModelState.Keys.Where(k => k.StartsWith("Input.Fields", StringComparison.Ordinal)).ToList())
        {
            ModelState.Remove(key);
        }

        if (!ModelState.IsValid || !await TryExecuteAsync(() => Mediator.Send(Input), prefix: string.Empty))
        {
            return Page();
        }

        Toast(L["Saved successfully."]);
        return RedirectToPage("Index");
    }
}
