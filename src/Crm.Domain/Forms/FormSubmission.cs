using Crm.Domain.Common;

namespace Crm.Domain.Forms;

/// <summary>A single answered field (stored as JSON inside the submission).</summary>
public sealed record FormFieldValue
{
    public string Key { get; set; } = string.Empty;

    /// <summary>Raw value: text, invariant number, ISO date, option value, entity id or stored file name.</summary>
    public string? Value { get; set; }

    /// <summary>Human-readable snapshot (lookup display name, original file name).</summary>
    public string? Display { get; set; }
}

/// <summary>
/// A filled-in dynamic form. It is a first-class trackable object: it can be discussed in chat,
/// have tasks / reminders attached and keeps its own activity timeline.
/// </summary>
public class FormSubmission : AuditableEntity, ITrackableEntity
{
    public Guid FormDefinitionId { get; set; }
    public FormDefinition? FormDefinition { get; set; }
    public string Title { get; set; } = string.Empty;
    public string? SubmittedByName { get; set; }
    public List<FormFieldValue> Values { get; set; } = [];

    public TrackableEntityType EntityType => TrackableEntityType.FormSubmission;
    public string DisplayName => Title;

    public string? GetValue(string key) => Values.FirstOrDefault(v => v.Key == key)?.Value;
}
