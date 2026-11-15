using Crm.Domain.Common;

namespace Crm.Domain.Sales;

public enum LeadStatus
{
    New = 1,
    Contacted = 2,
    Qualified = 3,
    Lost = 4,
    Converted = 5,
}

public enum LeadSource
{
    Website = 1,
    Referral = 2,
    Campaign = 3,
    ColdCall = 4,
    Exhibition = 5,
    Other = 6,
}

public class Lead : AuditableEntity, ITrackableEntity
{
    public string Name { get; set; } = string.Empty;
    public string? Company { get; set; }
    public string? Email { get; set; }
    public string? Phone { get; set; }
    public LeadSource Source { get; set; } = LeadSource.Website;
    public LeadStatus Status { get; set; } = LeadStatus.New;
    public decimal EstimatedValue { get; set; }
    public string? Notes { get; set; }
    public Guid? OwnerUserId { get; set; }
    public Guid? ConvertedCustomerId { get; private set; }

    public TrackableEntityType EntityType => TrackableEntityType.Lead;
    public string DisplayName => string.IsNullOrWhiteSpace(Company) ? Name : $"{Name} ({Company})";

    /// <summary>Turns the lead into a customer. A lead can be converted only once.</summary>
    public Customer ConvertToCustomer()
    {
        if (Status == LeadStatus.Converted)
        {
            throw new DomainException("This lead has already been converted.");
        }

        var isCompany = !string.IsNullOrWhiteSpace(Company);
        var customer = new Customer
        {
            Name = isCompany ? Company! : Name,
            Type = isCompany ? CustomerType.B2B : CustomerType.B2C,
            Email = Email,
            Phone = Phone,
            Notes = Notes,
            OwnerUserId = OwnerUserId,
        };

        if (isCompany)
        {
            var parts = Name.Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
            customer.Contacts.Add(new Contact
            {
                FirstName = parts.ElementAtOrDefault(0) ?? Name,
                LastName = parts.ElementAtOrDefault(1) ?? string.Empty,
                Email = Email,
                Phone = Phone,
                IsPrimary = true,
            });
        }

        Status = LeadStatus.Converted;
        ConvertedCustomerId = customer.Id;
        AddDomainEvent(new LeadConvertedEvent(Id, customer.Id));
        return customer;
    }
}

public sealed record LeadConvertedEvent(Guid LeadId, Guid CustomerId) : IDomainEvent;
