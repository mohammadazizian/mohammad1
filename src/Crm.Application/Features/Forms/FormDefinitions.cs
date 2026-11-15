using Crm.Domain.Forms;

namespace Crm.Application.Features.Forms;

public sealed record FormSummaryDto(
    Guid Id,
    string Code,
    LocalizedText Title,
    LocalizedText Description,
    bool IsPublished,
    int FieldCount,
    int SubmissionCount);

public sealed record GetFormsQuery(bool PublishedOnly = false) : IRequest<IReadOnlyList<FormSummaryDto>>;

internal sealed class GetFormsQueryHandler(IApplicationDbContext db) : IRequestHandler<GetFormsQuery, IReadOnlyList<FormSummaryDto>>
{
    public async Task<IReadOnlyList<FormSummaryDto>> Handle(GetFormsQuery request, CancellationToken cancellationToken)
    {
        var forms = await db.FormDefinitions.AsNoTracking()
            .Where(f => !request.PublishedOnly || f.IsPublished)
            .OrderBy(f => f.Code)
            .ToListAsync(cancellationToken);

        var counts = await db.FormSubmissions.AsNoTracking()
            .GroupBy(s => s.FormDefinitionId)
            .Select(g => new { FormId = g.Key, Count = g.Count() })
            .ToDictionaryAsync(g => g.FormId, g => g.Count, cancellationToken);

        return forms
            .Select(f => new FormSummaryDto(
                f.Id, f.Code, f.Title, f.Description, f.IsPublished, f.Fields.Count, counts.GetValueOrDefault(f.Id)))
            .ToList();
    }
}

public sealed record FormDto(
    Guid Id,
    string Code,
    LocalizedText Title,
    LocalizedText Description,
    bool IsPublished,
    IReadOnlyList<FormField> Fields);

/// <summary>Loads a form schema by id or by code.</summary>
public sealed record GetFormQuery(Guid? Id = null, string? Code = null) : IRequest<FormDto>;

internal sealed class GetFormQueryHandler(IApplicationDbContext db) : IRequestHandler<GetFormQuery, FormDto>
{
    public async Task<FormDto> Handle(GetFormQuery request, CancellationToken cancellationToken)
    {
        var form = await db.FormDefinitions.AsNoTracking()
            .FirstOrDefaultAsync(f => request.Id != null ? f.Id == request.Id : f.Code == request.Code, cancellationToken)
            ?? throw new NotFoundException(nameof(FormDefinition), (object?)request.Id ?? request.Code ?? "?");
        return form.ToDto();
    }
}

internal static class FormMapping
{
    public static FormDto ToDto(this FormDefinition form) => new(
        form.Id, form.Code, form.Title, form.Description, form.IsPublished, form.Fields.OrderBy(f => f.Order).ToList());
}

public sealed class UpsertFormCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string Code { get; set; } = string.Empty;
    public string TitleEn { get; set; } = string.Empty;
    public string TitleFa { get; set; } = string.Empty;
    public string? DescriptionEn { get; set; }
    public string? DescriptionFa { get; set; }
    public bool IsPublished { get; set; } = true;
    public List<FormField> Fields { get; set; } = [];
}

internal sealed class UpsertFormCommandValidator : AbstractValidator<UpsertFormCommand>
{
    public UpsertFormCommandValidator()
    {
        RuleFor(x => x.Code).NotEmpty().MaximumLength(40);
        RuleFor(x => x.TitleEn).NotEmpty().MaximumLength(200);
        RuleFor(x => x.TitleFa).MaximumLength(200);
        RuleFor(x => x.Fields).NotEmpty().WithMessage("A form needs at least one field.");
        RuleFor(x => x.Fields).Must(f => f.Count <= 100).WithMessage("A form can have at most 100 fields.");
        RuleForEach(x => x.Fields).ChildRules(field =>
        {
            field.RuleFor(f => f.Key).NotEmpty().MaximumLength(50);
            field.RuleFor(f => f.Type).IsInEnum();
            field.RuleFor(f => f.Label.En).NotEmpty().WithMessage("Every field needs an English label.");
            field.RuleFor(f => f).Must(f => f.Min is null || f.Max is null || f.Min <= f.Max)
                .WithMessage("Min must not be greater than max.");
        });
    }
}

internal sealed class UpsertFormCommandHandler(IApplicationDbContext db) : IRequestHandler<UpsertFormCommand, Guid>
{
    public async Task<Guid> Handle(UpsertFormCommand request, CancellationToken cancellationToken)
    {
        var code = request.Code.Trim().ToLowerInvariant();
        if (await db.FormDefinitions.AnyAsync(f => f.Code == code && f.Id != request.Id, cancellationToken))
        {
            throw new AppValidationException(nameof(request.Code), $"Form code '{code}' is already in use.");
        }

        FormDefinition form;
        if (request.Id is { } id)
        {
            form = await db.FormDefinitions.FirstOrDefaultAsync(f => f.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(FormDefinition), id);
        }
        else
        {
            form = new FormDefinition();
            form.SetCode(code);
            db.FormDefinitions.Add(form);
        }

        // The code is the permission key of the form, so it is immutable after creation.
        form.Title = new LocalizedText(request.TitleEn.Trim(), request.TitleFa?.Trim() ?? string.Empty);
        form.Description = new LocalizedText(request.DescriptionEn?.Trim() ?? string.Empty, request.DescriptionFa?.Trim() ?? string.Empty);
        form.IsPublished = request.IsPublished;
        form.SetFields(request.Fields);

        await db.SaveChangesAsync(cancellationToken);
        return form.Id;
    }
}

public sealed record DeleteFormCommand(Guid Id) : IRequest;

internal sealed class DeleteFormCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteFormCommand>
{
    public async Task Handle(DeleteFormCommand request, CancellationToken cancellationToken)
    {
        var form = await db.FormDefinitions.FirstOrDefaultAsync(f => f.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(FormDefinition), request.Id);

        // Submissions cannot outlive their schema.
        var submissions = await db.FormSubmissions.Where(s => s.FormDefinitionId == form.Id).ToListAsync(cancellationToken);
        db.FormSubmissions.RemoveRange(submissions);
        db.FormDefinitions.Remove(form);
        await db.SaveChangesAsync(cancellationToken);
    }
}
