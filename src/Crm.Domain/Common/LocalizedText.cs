namespace Crm.Domain.Common;

/// <summary>Value object holding a text in every supported language.</summary>
public sealed record LocalizedText
{
    public string En { get; set; } = string.Empty;
    public string Fa { get; set; } = string.Empty;

    public LocalizedText()
    {
    }

    public LocalizedText(string en, string fa)
    {
        En = en;
        Fa = fa;
    }

    /// <summary>Returns the text for a culture name such as "fa-IR", falling back to the other language.</summary>
    public string Get(string? cultureName)
    {
        var preferFa = cultureName?.StartsWith("fa", StringComparison.OrdinalIgnoreCase) == true;
        var (first, second) = preferFa ? (Fa, En) : (En, Fa);
        return string.IsNullOrWhiteSpace(first) ? second : first;
    }

    public override string ToString() => En;
}
