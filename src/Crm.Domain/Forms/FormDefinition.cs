using System.Globalization;
using System.Text.RegularExpressions;
using Crm.Domain.Common;

namespace Crm.Domain.Forms;

public enum FormFieldType
{
    Text = 1,
    Number = 2,
    Dropdown = 3,
    Date = 4,
    File = 5,
    EntityLookup = 6,
    TextArea = 7,
}

public sealed record FormFieldOption
{
    public string Value { get; set; } = string.Empty;
    public LocalizedText Label { get; set; } = new();
}

/// <summary>One field of a dynamic form schema (stored as JSON inside the form definition).</summary>
public sealed record FormField
{
    public string Key { get; set; } = string.Empty;
    public FormFieldType Type { get; set; } = FormFieldType.Text;
    public LocalizedText Label { get; set; } = new();
    public int Order { get; set; }

    // Validation rules
    public bool Required { get; set; }
    public decimal? Min { get; set; }
    public decimal? Max { get; set; }
    public int? MaxLength { get; set; }
    public string? Pattern { get; set; }

    public List<FormFieldOption> Options { get; set; } = [];
    public TrackableEntityType? LookupEntityType { get; set; }

    /// <summary>Validates a raw submitted value. Returns an error code, or null when valid.</summary>
    public FormFieldError? Validate(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return Required ? FormFieldError.Required : null;
        }

        switch (Type)
        {
            case FormFieldType.Number:
                if (!decimal.TryParse(value, NumberStyles.Number, CultureInfo.InvariantCulture, out var number))
                {
                    return FormFieldError.InvalidNumber;
                }

                if (number < Min || number > Max)
                {
                    return FormFieldError.OutOfRange;
                }

                break;
            case FormFieldType.Date:
                if (!DateOnly.TryParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
                {
                    return FormFieldError.InvalidDate;
                }

                break;
            case FormFieldType.Dropdown:
                if (Options.All(o => o.Value != value))
                {
                    return FormFieldError.InvalidOption;
                }

                break;
            case FormFieldType.EntityLookup:
                if (!Guid.TryParse(value, out _))
                {
                    return FormFieldError.InvalidOption;
                }

                break;
            case FormFieldType.Text or FormFieldType.TextArea:
                if (value.Length > MaxLength)
                {
                    return FormFieldError.TooLong;
                }

                if (!string.IsNullOrEmpty(Pattern) && !SafeIsMatch(value, Pattern))
                {
                    return FormFieldError.PatternMismatch;
                }

                break;
        }

        return null;
    }

    private static bool SafeIsMatch(string value, string pattern)
    {
        try
        {
            return Regex.IsMatch(value, pattern, RegexOptions.None, TimeSpan.FromMilliseconds(200));
        }
        catch (Exception ex) when (ex is ArgumentException or RegexMatchTimeoutException)
        {
            return false;
        }
    }
}

public enum FormFieldError
{
    Required,
    InvalidNumber,
    OutOfRange,
    InvalidDate,
    InvalidOption,
    TooLong,
    PatternMismatch,
}

/// <summary>An admin-designed form. Title, description and the whole field schema live in JSON columns.</summary>
public partial class FormDefinition : AuditableEntity
{
    public string Code { get; private set; } = string.Empty;
    public LocalizedText Title { get; set; } = new();
    public LocalizedText Description { get; set; } = new();
    public bool IsPublished { get; set; } = true;
    public List<FormField> Fields { get; set; } = [];

    public ICollection<FormSubmission> Submissions { get; } = [];

    public void SetCode(string code)
    {
        var normalized = (code ?? string.Empty).Trim().ToLowerInvariant();
        if (!CodePattern().IsMatch(normalized))
        {
            throw new DomainException("Form code must be 2-40 characters of a-z, 0-9 and '-'.");
        }

        Code = normalized;
    }

    /// <summary>Replaces the schema, enforcing unique keys and valid dropdown / lookup settings.</summary>
    public void SetFields(IEnumerable<FormField> fields)
    {
        var list = fields.ToList();
        for (var i = 0; i < list.Count; i++)
        {
            var field = list[i];
            field.Key = field.Key.Trim();
            field.Order = i;

            if (!KeyPattern().IsMatch(field.Key))
            {
                throw new DomainException($"Invalid field key '{field.Key}': use letters, digits and '_' (must start with a letter).");
            }

            if (field.Type == FormFieldType.Dropdown && field.Options.Count == 0)
            {
                throw new DomainException($"Dropdown field '{field.Key}' needs at least one option.");
            }

            if (field.Type == FormFieldType.EntityLookup && field.LookupEntityType is null)
            {
                throw new DomainException($"Lookup field '{field.Key}' needs a target entity type.");
            }

            if (field.Type != FormFieldType.Dropdown)
            {
                field.Options = [];
            }

            if (field.Type != FormFieldType.EntityLookup)
            {
                field.LookupEntityType = null;
            }
        }

        var duplicate = list.GroupBy(f => f.Key, StringComparer.OrdinalIgnoreCase).FirstOrDefault(g => g.Count() > 1);
        if (duplicate is not null)
        {
            throw new DomainException($"Duplicate field key '{duplicate.Key}'.");
        }

        Fields = list;
    }

    [GeneratedRegex("^[a-z0-9][a-z0-9-]{1,39}$")]
    private static partial Regex CodePattern();

    [GeneratedRegex("^[A-Za-z][A-Za-z0-9_]{0,49}$")]
    private static partial Regex KeyPattern();
}
