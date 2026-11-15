using Crm.Domain.Sales;

namespace Crm.Application.Features.Customers;

public sealed record CustomerListItem(Guid Id, string Name, CustomerType Type, string? Email, string? Phone, string? City, int OpenDeals, DateTime CreatedAt);

public sealed record GetCustomersQuery : PagedQuery, IRequest<PagedList<CustomerListItem>>
{
    public CustomerType? Type { get; init; }
}

internal sealed class GetCustomersQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetCustomersQuery, PagedList<CustomerListItem>>
{
    public Task<PagedList<CustomerListItem>> Handle(GetCustomersQuery request, CancellationToken cancellationToken)
    {
        var query = db.Customers.AsNoTracking();

        if (!string.IsNullOrWhiteSpace(request.Search))
        {
            var term = request.Search.Trim();
            query = query.Where(c => c.Name.Contains(term) || c.Email!.Contains(term) || c.Phone!.Contains(term));
        }

        if (request.Type is not null)
        {
            query = query.Where(c => c.Type == request.Type);
        }

        return query
            .OrderBy(c => c.Name)
            .Select(c => new CustomerListItem(
                c.Id, c.Name, c.Type, c.Email, c.Phone, c.Address.City,
                c.Deals.Count(d => d.ClosedAt == null), c.CreatedAt))
            .ToPagedListAsync(request, cancellationToken);
    }
}

public sealed record ContactDto(Guid Id, string FullName, string? Email, string? Phone, string? Position, bool IsPrimary);

public sealed record InteractionDto(Guid Id, InteractionType Type, string Subject, string? Notes, DateTime OccurredAt, string? UserName);

public sealed record CustomerDealDto(Guid Id, string Title, decimal Amount, LocalizedText Stage, bool IsWon, bool IsLost);

public sealed record CustomerDetailsDto(
    Guid Id,
    string Name,
    CustomerType Type,
    string? Email,
    string? Phone,
    string? TaxId,
    string? Notes,
    Address Address,
    DateTime CreatedAt,
    IReadOnlyList<ContactDto> Contacts,
    IReadOnlyList<InteractionDto> Interactions,
    IReadOnlyList<CustomerDealDto> Deals);

public sealed record GetCustomerDetailsQuery(Guid Id) : IRequest<CustomerDetailsDto>;

internal sealed class GetCustomerDetailsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetCustomerDetailsQuery, CustomerDetailsDto>
{
    public async Task<CustomerDetailsDto> Handle(GetCustomerDetailsQuery request, CancellationToken cancellationToken)
    {
        var customer = await db.Customers.AsNoTracking()
            .Include(c => c.Contacts)
            .Include(c => c.Interactions)
            .Include(c => c.Deals).ThenInclude(d => d.Stage)
            .FirstOrDefaultAsync(c => c.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Customer), request.Id);

        return new CustomerDetailsDto(
            customer.Id, customer.Name, customer.Type, customer.Email, customer.Phone, customer.TaxId, customer.Notes,
            customer.Address, customer.CreatedAt,
            customer.Contacts.OrderByDescending(c => c.IsPrimary).ThenBy(c => c.FirstName)
                .Select(c => new ContactDto(c.Id, c.FullName, c.Email, c.Phone, c.Position, c.IsPrimary)).ToList(),
            customer.Interactions.OrderByDescending(i => i.OccurredAt)
                .Select(i => new InteractionDto(i.Id, i.Type, i.Subject, i.Notes, i.OccurredAt, i.UserName)).ToList(),
            customer.Deals.OrderByDescending(d => d.CreatedAt)
                .Select(d => new CustomerDealDto(d.Id, d.Title, d.Amount, d.Stage!.Name, d.Stage.IsWon, d.Stage.IsLost)).ToList());
    }
}

public sealed record GetCustomerOptionsQuery : IRequest<IReadOnlyList<OptionDto>>;

internal sealed class GetCustomerOptionsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetCustomerOptionsQuery, IReadOnlyList<OptionDto>>
{
    public async Task<IReadOnlyList<OptionDto>> Handle(GetCustomerOptionsQuery request, CancellationToken cancellationToken) =>
        await db.Customers.AsNoTracking()
            .OrderBy(c => c.Name)
            .Select(c => new OptionDto(c.Id.ToString(), c.Name))
            .ToListAsync(cancellationToken);
}
