using Crm.Domain.Collaboration;
using Crm.Domain.Sales;

namespace Crm.Application.Features.Leads;

public sealed record LeadDto(
    Guid Id,
    string Name,
    string? Company,
    string? Email,
    string? Phone,
    LeadSource Source,
    LeadStatus Status,
    decimal EstimatedValue,
    string? Notes,
    Guid? ConvertedCustomerId,
    DateTime CreatedAt)
{
    public string DisplayName => string.IsNullOrWhiteSpace(Company) ? Name : $"{Name} ({Company})";
}

public sealed record GetLeadsQuery : PagedQuery, IRequest<PagedList<LeadDto>>
{
    public LeadStatus? Status { get; init; }
}

internal sealed class GetLeadsQueryHandler(IApplicationDbContext db) : IRequestHandler<GetLeadsQuery, PagedList<LeadDto>>
{
    public Task<PagedList<LeadDto>> Handle(GetLeadsQuery request, CancellationToken cancellationToken)
    {
        var query = db.Leads.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(request.Search))
        {
            var term = request.Search.Trim();
            query = query.Where(l => l.Name.Contains(term) || l.Company!.Contains(term) || l.Email!.Contains(term));
        }

        if (request.Status is not null)
        {
            query = query.Where(l => l.Status == request.Status);
        }

        return query.OrderByDescending(l => l.CreatedAt).Select(LeadMapping.ToDto).ToPagedListAsync(request, cancellationToken);
    }
}

public sealed record GetLeadQuery(Guid Id) : IRequest<LeadDto>;

internal sealed class GetLeadQueryHandler(IApplicationDbContext db) : IRequestHandler<GetLeadQuery, LeadDto>
{
    public async Task<LeadDto> Handle(GetLeadQuery request, CancellationToken cancellationToken) =>
        await db.Leads.AsNoTracking().Where(l => l.Id == request.Id).Select(LeadMapping.ToDto).FirstOrDefaultAsync(cancellationToken)
        ?? throw new NotFoundException(nameof(Lead), request.Id);
}

internal static class LeadMapping
{
    public static readonly System.Linq.Expressions.Expression<Func<Lead, LeadDto>> ToDto = l => new LeadDto(
        l.Id, l.Name, l.Company, l.Email, l.Phone, l.Source, l.Status, l.EstimatedValue, l.Notes, l.ConvertedCustomerId, l.CreatedAt);
}

public sealed class UpsertLeadCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Company { get; set; }
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public LeadSource Source { get; set; } = LeadSource.Website;
    public LeadStatus Status { get; set; } = LeadStatus.New;
    public decimal EstimatedValue { get; set; }
    public string? Notes { get; set; }
}

internal sealed class UpsertLeadCommandValidator : AbstractValidator<UpsertLeadCommand>
{
    public UpsertLeadCommandValidator()
    {
        RuleFor(x => x.Name).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Company).MaximumLength(200);
        RuleFor(x => x.Email).EmailAddress().When(x => !string.IsNullOrWhiteSpace(x.Email));
        RuleFor(x => x.Source).IsInEnum();
        RuleFor(x => x.Status).IsInEnum().NotEqual(LeadStatus.Converted)
            .WithMessage("Use the convert action to convert a lead.");
        RuleFor(x => x.EstimatedValue).GreaterThanOrEqualTo(0);
    }
}

internal sealed class UpsertLeadCommandHandler(IApplicationDbContext db) : IRequestHandler<UpsertLeadCommand, Guid>
{
    public async Task<Guid> Handle(UpsertLeadCommand request, CancellationToken cancellationToken)
    {
        Lead lead;
        if (request.Id is { } id)
        {
            lead = await db.Leads.FirstOrDefaultAsync(l => l.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(Lead), id);
            if (lead.Status == LeadStatus.Converted)
            {
                throw new DomainException("A converted lead can no longer be edited.");
            }
        }
        else
        {
            lead = new Lead();
            db.Leads.Add(lead);
        }

        lead.Name = request.Name.Trim();
        lead.Company = request.Company?.Trim();
        lead.Email = request.Email?.Trim();
        lead.Phone = request.Phone?.Trim();
        lead.Source = request.Source;
        lead.Status = request.Status;
        lead.EstimatedValue = request.EstimatedValue;
        lead.Notes = request.Notes;

        await db.SaveChangesAsync(cancellationToken);
        return lead.Id;
    }
}

public sealed record DeleteLeadCommand(Guid Id) : IRequest;

internal sealed class DeleteLeadCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteLeadCommand>
{
    public async Task Handle(DeleteLeadCommand request, CancellationToken cancellationToken)
    {
        var lead = await db.Leads.FirstOrDefaultAsync(l => l.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Lead), request.Id);
        db.Leads.Remove(lead);
        await db.SaveChangesAsync(cancellationToken);
    }
}

/// <summary>Converts a lead into a customer and returns the new customer id.</summary>
public sealed record ConvertLeadCommand(Guid Id) : IRequest<Guid>;

internal sealed class ConvertLeadCommandHandler(IApplicationDbContext db) : IRequestHandler<ConvertLeadCommand, Guid>
{
    public async Task<Guid> Handle(ConvertLeadCommand request, CancellationToken cancellationToken)
    {
        var lead = await db.Leads.FirstOrDefaultAsync(l => l.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Lead), request.Id);

        var customer = lead.ConvertToCustomer();
        db.Customers.Add(customer);
        db.ActivityLogs.Add(ActivityLog.For(lead, ActivityAction.Converted, customer.Name));

        await db.SaveChangesAsync(cancellationToken);
        return customer.Id;
    }
}
