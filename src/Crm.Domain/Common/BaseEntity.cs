namespace Crm.Domain.Common;

/// <summary>Root of every persisted entity. Carries identity and pending domain events.</summary>
public abstract class BaseEntity
{
    private readonly List<IDomainEvent> _domainEvents = [];

    public Guid Id { get; set; } = Guid.CreateVersion7();

    public IReadOnlyCollection<IDomainEvent> DomainEvents => _domainEvents.AsReadOnly();

    public void AddDomainEvent(IDomainEvent domainEvent) => _domainEvents.Add(domainEvent);

    public void ClearDomainEvents() => _domainEvents.Clear();
}

/// <summary>Marker for domain events. Dispatched after a successful save.</summary>
public interface IDomainEvent
{
    DateTime OccurredAt => DateTime.UtcNow;
}

public interface IAuditable
{
    DateTime CreatedAt { get; set; }
    Guid? CreatedBy { get; set; }
    DateTime? ModifiedAt { get; set; }
    Guid? ModifiedBy { get; set; }
}

public interface ISoftDelete
{
    bool IsDeleted { get; set; }
    DateTime? DeletedAt { get; set; }
    Guid? DeletedBy { get; set; }
}

/// <summary>Entity with automatic audit stamps and soft-delete (both applied by an EF Core interceptor).</summary>
public abstract class AuditableEntity : BaseEntity, IAuditable, ISoftDelete
{
    public DateTime CreatedAt { get; set; }
    public Guid? CreatedBy { get; set; }
    public DateTime? ModifiedAt { get; set; }
    public Guid? ModifiedBy { get; set; }
    public bool IsDeleted { get; set; }
    public DateTime? DeletedAt { get; set; }
    public Guid? DeletedBy { get; set; }
}

/// <summary>Raised when a business rule of the domain is violated.</summary>
public class DomainException(string message) : Exception(message);
