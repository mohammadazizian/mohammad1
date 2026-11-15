using Crm.Domain.Sales;

namespace Crm.Application.Features.Customers;

public sealed class UpsertCustomerCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public CustomerType Type { get; set; } = CustomerType.B2B;
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public string? TaxId { get; set; }
    public string? Notes { get; set; }
    public string? Street { get; set; }
    public string? City { get; set; }
    public string? Country { get; set; }
    public string? PostalCode { get; set; }
}

internal sealed class UpsertCustomerCommandValidator : AbstractValidator<UpsertCustomerCommand>
{
    public UpsertCustomerCommandValidator()
    {
        RuleFor(x => x.Name).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Type).IsInEnum();
        RuleFor(x => x.Email).EmailAddress().MaximumLength(256).When(x => !string.IsNullOrWhiteSpace(x.Email));
        RuleFor(x => x.Phone).MaximumLength(32);
        RuleFor(x => x.TaxId).MaximumLength(32);
        RuleFor(x => x.Notes).MaximumLength(2000);
    }
}

internal sealed class UpsertCustomerCommandHandler(IApplicationDbContext db) : IRequestHandler<UpsertCustomerCommand, Guid>
{
    public async Task<Guid> Handle(UpsertCustomerCommand request, CancellationToken cancellationToken)
    {
        Customer customer;
        if (request.Id is { } id)
        {
            customer = await db.Customers.FirstOrDefaultAsync(c => c.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(Customer), id);
        }
        else
        {
            customer = new Customer();
            db.Customers.Add(customer);
        }

        customer.Name = request.Name.Trim();
        customer.Type = request.Type;
        customer.Email = request.Email?.Trim();
        customer.Phone = request.Phone?.Trim();
        customer.TaxId = request.TaxId?.Trim();
        customer.Notes = request.Notes;
        customer.Address = new Address
        {
            Street = request.Street,
            City = request.City,
            Country = request.Country,
            PostalCode = request.PostalCode,
        };

        await db.SaveChangesAsync(cancellationToken);
        return customer.Id;
    }
}

public sealed record DeleteCustomerCommand(Guid Id) : IRequest;

internal sealed class DeleteCustomerCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteCustomerCommand>
{
    public async Task Handle(DeleteCustomerCommand request, CancellationToken cancellationToken)
    {
        var customer = await db.Customers.FirstOrDefaultAsync(c => c.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Customer), request.Id);

        if (await db.Deals.AnyAsync(d => d.CustomerId == request.Id && d.ClosedAt == null, cancellationToken))
        {
            throw new DomainException("A customer with open deals cannot be deleted.");
        }

        db.Customers.Remove(customer);
        await db.SaveChangesAsync(cancellationToken);
    }
}

public sealed class AddContactCommand : IRequest<Guid>
{
    public Guid CustomerId { get; set; }
    public string FirstName { get; set; } = string.Empty;
    public string LastName { get; set; } = string.Empty;
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public string? Position { get; set; }
    public bool IsPrimary { get; set; }
}

internal sealed class AddContactCommandValidator : AbstractValidator<AddContactCommand>
{
    public AddContactCommandValidator()
    {
        RuleFor(x => x.FirstName).NotEmpty().MaximumLength(100);
        RuleFor(x => x.LastName).MaximumLength(100);
        RuleFor(x => x.Email).EmailAddress().When(x => !string.IsNullOrWhiteSpace(x.Email));
    }
}

internal sealed class AddContactCommandHandler(IApplicationDbContext db) : IRequestHandler<AddContactCommand, Guid>
{
    public async Task<Guid> Handle(AddContactCommand request, CancellationToken cancellationToken)
    {
        if (!await db.Customers.AnyAsync(c => c.Id == request.CustomerId, cancellationToken))
        {
            throw new NotFoundException(nameof(Customer), request.CustomerId);
        }

        if (request.IsPrimary)
        {
            var currentPrimaries = await db.Contacts
                .Where(c => c.CustomerId == request.CustomerId && c.IsPrimary)
                .ToListAsync(cancellationToken);
            currentPrimaries.ForEach(c => c.IsPrimary = false);
        }

        var contact = new Contact
        {
            CustomerId = request.CustomerId,
            FirstName = request.FirstName.Trim(),
            LastName = request.LastName?.Trim() ?? string.Empty,
            Email = request.Email,
            Phone = request.Phone,
            Position = request.Position,
            IsPrimary = request.IsPrimary,
        };
        db.Contacts.Add(contact);
        await db.SaveChangesAsync(cancellationToken);
        return contact.Id;
    }
}

public sealed record DeleteContactCommand(Guid Id) : IRequest;

internal sealed class DeleteContactCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteContactCommand>
{
    public async Task Handle(DeleteContactCommand request, CancellationToken cancellationToken)
    {
        var contact = await db.Contacts.FirstOrDefaultAsync(c => c.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Contact), request.Id);
        db.Contacts.Remove(contact);
        await db.SaveChangesAsync(cancellationToken);
    }
}

public sealed class AddInteractionCommand : IRequest<Guid>
{
    public Guid CustomerId { get; set; }
    public InteractionType Type { get; set; } = InteractionType.Call;
    public string Subject { get; set; } = string.Empty;
    public string? Notes { get; set; }
}

internal sealed class AddInteractionCommandValidator : AbstractValidator<AddInteractionCommand>
{
    public AddInteractionCommandValidator()
    {
        RuleFor(x => x.Subject).NotEmpty().MaximumLength(200);
        RuleFor(x => x.Type).IsInEnum();
        RuleFor(x => x.Notes).MaximumLength(4000);
    }
}

internal sealed class AddInteractionCommandHandler(IApplicationDbContext db, ICurrentUser currentUser, TimeProvider clock)
    : IRequestHandler<AddInteractionCommand, Guid>
{
    public async Task<Guid> Handle(AddInteractionCommand request, CancellationToken cancellationToken)
    {
        if (!await db.Customers.AnyAsync(c => c.Id == request.CustomerId, cancellationToken))
        {
            throw new NotFoundException(nameof(Customer), request.CustomerId);
        }

        var interaction = new Interaction
        {
            CustomerId = request.CustomerId,
            Type = request.Type,
            Subject = request.Subject.Trim(),
            Notes = request.Notes,
            OccurredAt = clock.GetUtcNow().UtcDateTime,
            UserName = currentUser.DisplayName ?? currentUser.UserName,
        };
        db.Interactions.Add(interaction);
        await db.SaveChangesAsync(cancellationToken);
        return interaction.Id;
    }
}
