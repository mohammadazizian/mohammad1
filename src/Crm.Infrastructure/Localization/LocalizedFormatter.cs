using System.Globalization;
using Microsoft.Extensions.Options;

namespace Crm.Infrastructure.Localization;

public sealed class RegionalOptions
{
    public const string SectionName = "Regional";

    /// <summary>IANA id of the business time zone used to display and read date-times.</summary>
    public string TimeZone { get; set; } = "Asia/Tehran";

    /// <summary>Currency patterns per language; {0} is replaced by the formatted amount.</summary>
    public string CurrencyFormatEn { get; set; } = "${0}";
    public string CurrencyFormatFa { get; set; } = "{0} دلار";
    public int CurrencyDecimals { get; set; }
}

public sealed class CultureContext : ICultureContext
{
    public string CultureName => CultureInfo.CurrentUICulture.Name;
    public bool IsRtl => CultureInfo.CurrentUICulture.TextInfo.IsRightToLeft;
    public bool IsPersian => CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "fa";
}

/// <summary>
/// Formats dates with the Jalali (Persian) calendar and Persian digits for fa-IR and with the
/// Gregorian calendar for every other language. Independent of the OS globalization data.
/// </summary>
public sealed class LocalizedFormatter : ILocalizedFormatter
{
    private static readonly PersianCalendar Persian = new();

    private static readonly string[] PersianMonths =
        ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];

    private readonly ICultureContext _culture;
    private readonly RegionalOptions _options;
    private readonly TimeProvider _clock;
    private readonly TimeZoneInfo _timeZone;

    public LocalizedFormatter(ICultureContext culture, IOptions<RegionalOptions> options, TimeProvider clock)
    {
        _culture = culture;
        _options = options.Value;
        _clock = clock;
        _timeZone = ResolveTimeZone(_options.TimeZone);
    }

    public string Date(DateTime? utc)
    {
        if (utc is null)
        {
            return "—";
        }

        var local = ToLocal(utc.Value);
        return _culture.IsPersian
            ? PersianDigits($"{Persian.GetDayOfMonth(local)} {PersianMonths[Persian.GetMonth(local) - 1]} {Persian.GetYear(local)}")
            : local.ToString("MMM d, yyyy", CultureInfo.InvariantCulture);
    }

    public string DateTime(DateTime? utc)
    {
        if (utc is null)
        {
            return "—";
        }

        var local = ToLocal(utc.Value);
        return _culture.IsPersian
            ? $"{Date(utc)}، {PersianDigits(local.ToString("HH:mm", CultureInfo.InvariantCulture))}"
            : $"{Date(utc)}, {local.ToString("HH:mm", CultureInfo.InvariantCulture)}";
    }

    public string RelativeTime(DateTime utc)
    {
        var elapsed = _clock.GetUtcNow().UtcDateTime - utc;
        var persian = _culture.IsPersian;

        if (elapsed < TimeSpan.Zero || elapsed >= TimeSpan.FromDays(7))
        {
            return Date(utc);
        }

        if (elapsed < TimeSpan.FromMinutes(1))
        {
            return persian ? "همین حالا" : "just now";
        }

        var (value, en, fa) = elapsed switch
        {
            _ when elapsed < TimeSpan.FromHours(1) => ((int)elapsed.TotalMinutes, "min", "دقیقه"),
            _ when elapsed < TimeSpan.FromDays(1) => ((int)elapsed.TotalHours, "h", "ساعت"),
            _ => ((int)elapsed.TotalDays, "d", "روز"),
        };

        return persian ? $"{PersianDigits(value.ToString(CultureInfo.InvariantCulture))} {fa} پیش" : $"{value} {en} ago";
    }

    public string Currency(decimal amount)
    {
        var number = FormatNumber(amount, _options.CurrencyDecimals);
        return string.Format(CultureInfo.InvariantCulture, _culture.IsPersian ? _options.CurrencyFormatFa : _options.CurrencyFormatEn, number);
    }

    public string Number(decimal value) => FormatNumber(value, decimal.Truncate(value) == value ? 0 : 2);

    public DateTime ToLocal(DateTime utc) =>
        TimeZoneInfo.ConvertTimeFromUtc(System.DateTime.SpecifyKind(utc, DateTimeKind.Utc), _timeZone);

    public DateTime ToUtc(DateTime local) =>
        TimeZoneInfo.ConvertTimeToUtc(System.DateTime.SpecifyKind(local, DateTimeKind.Unspecified), _timeZone);

    private string FormatNumber(decimal value, int decimals)
    {
        var text = value.ToString("N" + decimals, CultureInfo.InvariantCulture);
        return _culture.IsPersian ? PersianDigits(text).Replace(',', '٬').Replace('.', '٫') : text;
    }

    private static string PersianDigits(string text) =>
        string.Create(text.Length, text, static (span, source) =>
        {
            for (var i = 0; i < source.Length; i++)
            {
                span[i] = source[i] is >= '0' and <= '9' ? (char)('۰' + (source[i] - '0')) : source[i];
            }
        });

    private static TimeZoneInfo ResolveTimeZone(string id)
    {
        try
        {
            return TimeZoneInfo.FindSystemTimeZoneById(id);
        }
        catch (Exception ex) when (ex is TimeZoneNotFoundException or InvalidTimeZoneException)
        {
            return TimeZoneInfo.Utc;
        }
    }
}
