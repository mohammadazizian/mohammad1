namespace Crm.Domain.Common;

/// <summary>
/// The kinds of business objects that can take part in the polymorphic engine.
/// Add a member here (and implement <see cref="ITrackableEntity"/>) to make a new entity
/// chat-, task-, reminder- and activity-enabled without any new table.
/// </summary>
public enum TrackableEntityType
{
    Customer = 1,
    Product = 2,
    InventoryTransaction = 3,
    FormSubmission = 4,
    Lead = 5,
    Deal = 6,
}

/// <summary>
/// Polymorphic contract: anything implementing it can own chats, tasks, reminders and
/// activity logs through the (<see cref="EntityType"/>, Id) pair.
/// </summary>
public interface ITrackableEntity
{
    Guid Id { get; }
    TrackableEntityType EntityType { get; }
    string DisplayName { get; }
}

/// <summary>Polymorphic pointer to a trackable entity.</summary>
public readonly record struct EntityRef(TrackableEntityType Type, Guid Id)
{
    public static EntityRef Of(ITrackableEntity entity) => new(entity.EntityType, entity.Id);

    public override string ToString() => $"{Type}:{Id}";

    public static bool TryParse(string? value, out EntityRef reference)
    {
        reference = default;
        var parts = value?.Split(':', 2);
        if (parts is not { Length: 2 }
            || !Enum.TryParse<TrackableEntityType>(parts[0], ignoreCase: true, out var type)
            || !Enum.IsDefined(type)
            || !Guid.TryParse(parts[1], out var id))
        {
            return false;
        }

        reference = new EntityRef(type, id);
        return true;
    }
}
