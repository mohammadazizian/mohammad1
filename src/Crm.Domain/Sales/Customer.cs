using Crm.Domain.Common;

namespace Crm.Domain.Sales;

public enum CustomerType
{
    B2B = 1,
    B2C = 2,
}

/// <summary>Postal address value object (stored inline with its owner).</summary>
public sealed record Address
{
    public string? Street { get; set; }
    public string? City { get; set; }
    public string? Country { get; set; }
    public string? PostalCode { get; set; }
}

public class Customer : AuditableEntity, ITrackableEntity
{
    public string Name { get; set; } = string.Empty;
    public CustomerType Type { get; set; } = CustomerType.B2B;
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public string? TaxId { get; set; }
    public string? Notes { get; set; }
    public Guid? OwnerUserId { get; set; }
    public Address Address { get; set; } = new();

    public ICollection<Contact> Contacts { get; } = [];
    public ICollection<Interaction> Interactions { get; } = [];
    public ICollection<Deal> Deals { get; } = [];

    public TrackableEntityType EntityType => TrackableEntityType.Customer;
    public string DisplayName => Name;
}

public class Contact : AuditableEntity
{
    public Guid CustomerId { get; set; }
    public Customer? Customer { get; set; }
    public string FirstName { get; set; } = string.Empty;
    public string LastName { get; set; } = string.Empty;
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public string? Position { get; set; }
    public bool IsPrimary { get; set; }

    public string FullName => $"{FirstName} {LastName}".Trim();
}

public enum InteractionType
{
    Call = 1,
    Email = 2,
    Meeting = 3,
    Note = 4,
}

/// <summary>A touch-point with a customer (interaction history).</summary>
public class Interaction : AuditableEntity
{
    public Guid CustomerId { get; set; }
    public Customer? Customer { get; set; }
    public InteractionType Type { get; set; }
    public string Subject { get; set; } = string.Empty;
    public string? Notes { get; set; }
    public DateTime OccurredAt { get; set; }
    public string? UserName { get; set; }
}
