using Crm.Domain.Collaboration;

namespace Crm.Application.Common.Interfaces;

/// <summary>The user on whose behalf the current operation runs (empty for background jobs).</summary>
public interface ICurrentUser
{
    Guid? UserId { get; }
    string? UserName { get; }
    string? DisplayName { get; }
    bool IsAuthenticated { get; }
    IReadOnlyCollection<string> Roles { get; }
}

/// <summary>Stores uploaded files (chat attachments, form file fields).</summary>
public interface IFileStorage
{
    Task<StoredFile> SaveAsync(Stream content, string fileName, string? contentType, CancellationToken cancellationToken = default);

    /// <summary>Opens a stored file, or returns null when it does not exist.</summary>
    Stream? OpenRead(string storedName);
}

public sealed record StoredFile(string StoredName, string FileName, string ContentType, long Size);

/// <summary>Pushes real-time events to connected clients (SignalR).</summary>
public interface IRealtimeNotifier
{
    Task ChatMessagePostedAsync(EntityRef entity, Guid messageId, Guid? parentMessageId, CancellationToken cancellationToken = default);

    Task NotificationCreatedAsync(Notification notification, CancellationToken cancellationToken = default);
}

/// <summary>Creates in-app notifications and pushes them in real time.</summary>
public interface INotificationService
{
    Task NotifyAsync(
        IEnumerable<Guid> userIds,
        NotificationType type,
        string message,
        EntityRef? entity = null,
        CancellationToken cancellationToken = default);
}

/// <summary>Resolves the polymorphic (EntityType, EntityId) pair to actual objects.</summary>
public interface ITrackableEntityResolver
{
    Task<TrackableInfo?> ResolveAsync(EntityRef reference, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<TrackableInfo>> SearchAsync(
        string? term,
        TrackableEntityType? type = null,
        int take = 10,
        CancellationToken cancellationToken = default);
}

public sealed record TrackableInfo(TrackableEntityType Type, Guid Id, string DisplayName)
{
    public EntityRef Ref => new(Type, Id);
}

// ---- Localization ports -------------------------------------------------------------------

/// <summary>Language / direction of the current request.</summary>
public interface ICultureContext
{
    /// <summary>UI culture name, e.g. "fa-IR" or "en-US".</summary>
    string CultureName { get; }
    bool IsRtl { get; }
    bool IsPersian { get; }
}

/// <summary>Culture-aware formatting: Jalali calendar for fa-IR, Gregorian for en-US.</summary>
public interface ILocalizedFormatter
{
    string Date(DateTime? utc);
    string DateTime(DateTime? utc);
    string RelativeTime(DateTime utc);
    string Currency(decimal amount);
    string Number(decimal value);

    /// <summary>Converts a UTC instant to the application's business time zone.</summary>
    DateTime ToLocal(DateTime utc);

    /// <summary>Converts a wall-clock time of the business time zone to UTC.</summary>
    DateTime ToUtc(DateTime local);
}
