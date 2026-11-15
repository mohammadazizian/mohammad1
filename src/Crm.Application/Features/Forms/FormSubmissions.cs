using Crm.Domain.Forms;

namespace Crm.Application.Features.Forms;

/// <summary>Thrown when submitted values break the form's validation rules (field key → error code).</summary>
public sealed class FormValidationException(IReadOnlyDictionary<string, FormFieldError> errors)
    : Exception("The submitted form is invalid."), IExpectedException
{
    public IReadOnlyDictionary<string, FormFieldError> Errors { get; } = errors;
}

public sealed record SubmissionListItem(Guid Id, string Title, string? SubmittedByName, DateTime CreatedAt, IReadOnlyList<FormFieldValue> Values);

public sealed record GetSubmissionsQuery : PagedQuery, IRequest<PagedList<SubmissionListItem>>
{
    public Guid FormId { get; init; }
}

internal sealed class GetSubmissionsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetSubmissionsQuery, PagedList<SubmissionListItem>>
{
    public async Task<PagedList<SubmissionListItem>> Handle(GetSubmissionsQuery request, CancellationToken cancellationToken)
    {
        var query = db.FormSubmissions.AsNoTracking().Where(s => s.FormDefinitionId == request.FormId);
        if (!string.IsNullOrWhiteSpace(request.Search))
        {
            var term = request.Search.Trim();
            query = query.Where(s => s.Title.Contains(term) || s.SubmittedByName!.Contains(term));
        }

        var page = await query.OrderByDescending(s => s.CreatedAt).ToPagedListAsync(request, cancellationToken);
        return new PagedList<SubmissionListItem>(
            page.Items.Select(s => new SubmissionListItem(s.Id, s.Title, s.SubmittedByName, s.CreatedAt, s.Values)).ToList(),
            page.TotalCount, page.Page, page.PageSize);
    }
}

public sealed record SubmissionDto(
    Guid Id,
    string Title,
    string? SubmittedByName,
    DateTime CreatedAt,
    FormDto Form,
    IReadOnlyList<FormFieldValue> Values)
{
    public FormFieldValue? ValueOf(string key) => Values.FirstOrDefault(v => v.Key == key);
}

public sealed record GetSubmissionQuery(Guid Id) : IRequest<SubmissionDto>;

internal sealed class GetSubmissionQueryHandler(IApplicationDbContext db) : IRequestHandler<GetSubmissionQuery, SubmissionDto>
{
    public async Task<SubmissionDto> Handle(GetSubmissionQuery request, CancellationToken cancellationToken)
    {
        var submission = await db.FormSubmissions.AsNoTracking()
            .Include(s => s.FormDefinition)
            .FirstOrDefaultAsync(s => s.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(FormSubmission), request.Id);

        return new SubmissionDto(
            submission.Id, submission.Title, submission.SubmittedByName, submission.CreatedAt,
            submission.FormDefinition!.ToDto(), submission.Values);
    }
}

/// <summary>Creates (or, with <see cref="SubmissionId"/>, updates) a submission of a dynamic form.</summary>
public sealed record SubmitFormCommand(
    Guid FormId,
    IReadOnlyDictionary<string, string?> Values,
    IReadOnlyDictionary<string, StoredFile> Files,
    Guid? SubmissionId = null) : IRequest<Guid>;

internal sealed class SubmitFormCommandHandler(
    IApplicationDbContext db,
    ICurrentUser currentUser,
    ICultureContext culture,
    ITrackableEntityResolver resolver)
    : IRequestHandler<SubmitFormCommand, Guid>
{
    public async Task<Guid> Handle(SubmitFormCommand request, CancellationToken cancellationToken)
    {
        var form = await db.FormDefinitions.AsNoTracking().FirstOrDefaultAsync(f => f.Id == request.FormId, cancellationToken)
            ?? throw new NotFoundException(nameof(FormDefinition), request.FormId);

        FormSubmission? submission = null;
        if (request.SubmissionId is { } submissionId)
        {
            submission = await db.FormSubmissions
                .FirstOrDefaultAsync(s => s.Id == submissionId && s.FormDefinitionId == form.Id, cancellationToken)
                ?? throw new NotFoundException(nameof(FormSubmission), submissionId);
        }
        else if (!form.IsPublished)
        {
            throw new DomainException("This form is not published.");
        }

        var errors = new Dictionary<string, FormFieldError>();
        var values = new List<FormFieldValue>();

        foreach (var field in form.Fields.OrderBy(f => f.Order))
        {
            var value = await BuildValueAsync(field, request, submission, cancellationToken);
            if (field.Validate(value.Value) is { } error)
            {
                errors[field.Key] = error;
            }
            else if (field.Type == FormFieldType.EntityLookup && value.Value is not null && value.Display is null)
            {
                errors[field.Key] = FormFieldError.InvalidOption;
            }

            values.Add(value);
        }

        if (errors.Count != 0)
        {
            throw new FormValidationException(errors);
        }

        if (submission is null)
        {
            var sequence = await db.FormSubmissions.IgnoreQueryFilters()
                .CountAsync(s => s.FormDefinitionId == form.Id, cancellationToken) + 1;
            submission = new FormSubmission
            {
                FormDefinitionId = form.Id,
                Title = $"{form.Title.Get(culture.CultureName)} #{sequence}",
                SubmittedByName = currentUser.DisplayName ?? currentUser.UserName,
            };
            db.FormSubmissions.Add(submission);
        }

        submission.Values = values;
        await db.SaveChangesAsync(cancellationToken);
        return submission.Id;
    }

    private async Task<FormFieldValue> BuildValueAsync(
        FormField field,
        SubmitFormCommand request,
        FormSubmission? existing,
        CancellationToken cancellationToken)
    {
        var raw = request.Values.GetValueOrDefault(field.Key)?.Trim();
        raw = string.IsNullOrEmpty(raw) ? null : raw;

        switch (field.Type)
        {
            case FormFieldType.File:
                if (request.Files.TryGetValue(field.Key, out var file))
                {
                    return new FormFieldValue { Key = field.Key, Value = file.StoredName, Display = file.FileName };
                }

                // Keep the previously uploaded file when editing without a new upload.
                var previous = existing?.Values.FirstOrDefault(v => v.Key == field.Key);
                return new FormFieldValue { Key = field.Key, Value = previous?.Value, Display = previous?.Display };

            case FormFieldType.EntityLookup when Guid.TryParse(raw, out var entityId):
                var entity = await resolver.ResolveAsync(new EntityRef(field.LookupEntityType!.Value, entityId), cancellationToken);
                return new FormFieldValue { Key = field.Key, Value = raw, Display = entity?.DisplayName };

            default:
                return new FormFieldValue { Key = field.Key, Value = raw };
        }
    }
}

public sealed record DeleteSubmissionCommand(Guid Id) : IRequest;

internal sealed class DeleteSubmissionCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteSubmissionCommand>
{
    public async Task Handle(DeleteSubmissionCommand request, CancellationToken cancellationToken)
    {
        var submission = await db.FormSubmissions.FirstOrDefaultAsync(s => s.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(FormSubmission), request.Id);
        db.FormSubmissions.Remove(submission);
        await db.SaveChangesAsync(cancellationToken);
    }
}
