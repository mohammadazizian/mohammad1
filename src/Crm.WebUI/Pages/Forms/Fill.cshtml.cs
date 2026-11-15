using Crm.Application.Common.Interfaces;
using Crm.Application.Common.Models;
using Crm.Application.Common.Security;
using Crm.Application.Features.Forms;
using Crm.Domain.Forms;
using Crm.WebUI.Support;
using Microsoft.AspNetCore.Mvc;

namespace Crm.WebUI.Pages.Forms;

/// <summary>Creates or edits a submission of a dynamic form (rendered by <c>_DynamicFormRendererPartial</c>).</summary>
public class FillModel(IFileStorage files, ITrackableEntityResolver resolver) : FormPageModel
{
    private const int LookupLimit = 300;

    public Guid? SubmissionId { get; private set; }

    public DynamicFormViewModel Renderer { get; private set; } = default!;

    public async Task<IActionResult> OnGetAsync(string code, Guid? submissionId)
    {
        await LoadFormAsync(code, submissionId is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        SubmissionId = submissionId;

        var existing = await LoadExistingAsync(submissionId);
        var values = existing.ToDictionary(v => v.Key, v => v.Value);
        Renderer = await BuildRendererAsync(values, new Dictionary<string, string>(), existing);
        return Page();
    }

    public async Task<IActionResult> OnPostAsync(string code, Guid? submissionId)
    {
        await LoadFormAsync(code, submissionId is null ? Permissions.Actions.Create : Permissions.Actions.Edit);
        SubmissionId = submissionId;

        var values = Form.Fields
            .Where(f => f.Type != FormFieldType.File)
            .ToDictionary(f => f.Key, f => (string?)Request.Form[DynamicFormViewModel.InputName(f)].ToString());

        var errors = new Dictionary<string, string>();
        var uploads = new Dictionary<string, StoredFile>();
        try
        {
            foreach (var field in Form.Fields.Where(f => f.Type == FormFieldType.File))
            {
                if (Request.Form.Files[DynamicFormViewModel.InputName(field)] is { Length: > 0 } file)
                {
                    await using var stream = file.OpenReadStream();
                    uploads[field.Key] = await files.SaveAsync(stream, file.FileName, file.ContentType, HttpContext.RequestAborted);
                }
            }

            var id = await Mediator.Send(new SubmitFormCommand(Form.Id, values, uploads, submissionId));
            Toast(L["Saved successfully."]);
            return RedirectToPage("Submission", new { id });
        }
        catch (FormValidationException ex)
        {
            foreach (var (key, error) in ex.Errors)
            {
                errors[key] = Describe(Form.Fields.First(f => f.Key == key), error);
            }
        }
        catch (Crm.Application.Common.Exceptions.AppValidationException ex)
        {
            ModelState.AddModelError(string.Empty, string.Join(" ", ex.Errors.SelectMany(e => e.Value)));
        }
        catch (Crm.Domain.Common.DomainException ex)
        {
            ModelState.AddModelError(string.Empty, L[ex.Message]);
        }

        Renderer = await BuildRendererAsync(values, errors, await LoadExistingAsync(submissionId));
        return Page();
    }

    private async Task<IReadOnlyList<FormFieldValue>> LoadExistingAsync(Guid? submissionId) =>
        submissionId is null ? [] : (await Mediator.Send(new GetSubmissionQuery(submissionId.Value))).Values;

    private async Task<DynamicFormViewModel> BuildRendererAsync(
        IReadOnlyDictionary<string, string?> values,
        IReadOnlyDictionary<string, string> errors,
        IReadOnlyList<FormFieldValue> existing)
    {
        var lookups = new Dictionary<string, IReadOnlyList<OptionDto>>();
        foreach (var field in Form.Fields.Where(f => f is { Type: FormFieldType.EntityLookup, LookupEntityType: not null }))
        {
            var items = await resolver.SearchAsync(null, field.LookupEntityType, LookupLimit, HttpContext.RequestAborted);
            lookups[field.Key] = items.Select(i => new OptionDto(i.Id.ToString(), i.DisplayName)).ToList();
        }

        var existingFiles = existing
            .Where(v => Form.Fields.Any(f => f.Key == v.Key && f.Type == FormFieldType.File))
            .ToDictionary(v => v.Key);

        return new DynamicFormViewModel(Form, values, errors, lookups, existingFiles);
    }

    /// <summary>Localized message for a schema validation error.</summary>
    private string Describe(FormField field, FormFieldError error) => error switch
    {
        FormFieldError.Required => L["This field is required."],
        FormFieldError.InvalidNumber => L["Please enter a valid number."],
        FormFieldError.OutOfRange => L["The value must be between {0} and {1}.", Formatter.Number(field.Min ?? 0), field.Max is { } max ? Formatter.Number(max) : "∞"],
        FormFieldError.InvalidDate => L["Please enter a valid date."],
        FormFieldError.InvalidOption => L["Please choose one of the available options."],
        FormFieldError.TooLong => L["The text is too long (maximum {0} characters).", field.MaxLength ?? 0],
        FormFieldError.PatternMismatch => L["The value does not have the expected format."],
        _ => L["The value is invalid."],
    };
}
