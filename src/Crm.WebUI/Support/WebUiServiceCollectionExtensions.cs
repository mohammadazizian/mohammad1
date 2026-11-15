using System.Globalization;
using System.Text.Encodings.Web;
using System.Text.Unicode;
using Crm.Application.Common.Interfaces;
using Crm.WebUI.Services;
using FluentValidation;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Localization;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Localization;
using Microsoft.Extensions.WebEncoders;

namespace Crm.WebUI.Support;

public sealed class LocalizationSettings
{
    public const string SectionName = "Localization";

    /// <summary>The culture used for model binding and invariant-style parsing of numbers and dates.</summary>
    public const string DataCulture = "en-US";

    public string DefaultCulture { get; set; } = "en-US";

    /// <summary>UI languages offered by the language switcher. Add a culture here and ship its .resx files.</summary>
    public string[] SupportedCultures { get; set; } = ["en-US", "fa-IR"];
}

public static class WebUiServiceCollectionExtensions
{
    public static IServiceCollection AddWebUi(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddHttpContextAccessor();
        services.AddScoped<ICurrentUser, CurrentUser>();

        services.AddExceptionHandler<GlobalExceptionHandler>();
        services.AddProblemDetails();

        AddLocalization(services, configuration);

        services
            .AddRazorPages(options =>
            {
                // Secure by default: every page needs a signed-in user unless explicitly opened up.
                options.Conventions.AuthorizeFolder("/");
                options.Conventions.AllowAnonymousToPage("/Account/Login");
                options.Conventions.AllowAnonymousToPage("/Account/Language");
                options.Conventions.AllowAnonymousToPage("/Error");
            })
            .AddViewLocalization()
            .AddDataAnnotationsLocalization(options =>
                options.DataAnnotationLocalizerProvider = (_, factory) => factory.Create(typeof(SharedResource)));

        services.ConfigureApplicationCookie(options =>
        {
            options.LoginPath = "/Account/Login";
            options.LogoutPath = "/Account/Logout";
            options.AccessDeniedPath = "/Account/AccessDenied";
            options.Cookie.Name = "crm.auth";
            options.Cookie.HttpOnly = true;
            options.Cookie.SameSite = SameSiteMode.Lax;
            options.SlidingExpiration = true;
            options.ExpireTimeSpan = TimeSpan.FromHours(12);
        });

        // Keep auth cookies valid across container restarts by persisting the key ring.
        var keysPath = Path.GetFullPath(configuration["DataProtection:KeysPath"] ?? "App_Data/keys");
        services.AddDataProtection().SetApplicationName("crm").PersistKeysToFileSystem(Directory.CreateDirectory(keysPath));

        // Emit Persian (and any other Unicode) text as-is instead of numeric HTML entities.
        services.Configure<WebEncoderOptions>(options => options.TextEncoderSettings = new TextEncoderSettings(UnicodeRanges.All));

        services.AddAntiforgery(options => options.HeaderName = "RequestVerificationToken");
        services.Configure<FormOptions>(options => options.MultipartBodyLengthLimit = 60 * 1024 * 1024);
        services.Configure<ForwardedHeadersOptions>(options =>
        {
            options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
            options.KnownIPNetworks.Clear();
            options.KnownProxies.Clear();
        });

        return services;
    }

    private static void AddLocalization(IServiceCollection services, IConfiguration configuration)
    {
        var settings = configuration.GetSection(LocalizationSettings.SectionName).Get<LocalizationSettings>() ?? new LocalizationSettings();

        services.AddLocalization(options => options.ResourcesPath = "Resources");
        services.Configure<RequestLocalizationOptions>(options =>
        {
            // The *culture* stays en-US so posted numbers ("1250.50") and ISO dates always bind
            // the same way; only the *UI culture* follows the user's language. Display formatting
            // (Jalali dates, Persian digits, currency) is done by ILocalizedFormatter.
            options.DefaultRequestCulture = new RequestCulture(LocalizationSettings.DataCulture, settings.DefaultCulture);
            options.SupportedCultures = [new CultureInfo(LocalizationSettings.DataCulture)];
            options.SupportedUICultures = settings.SupportedCultures.Select(c => new CultureInfo(c)).ToList();
            options.RequestCultureProviders =
            [
                new CookieRequestCultureProvider { CookieName = LanguageCookie.Name },
            ];
        });
    }

    /// <summary>
    /// FluentValidation ships its own translations (Persian included); this translates the
    /// property names it embeds in messages through the shared resource file.
    /// </summary>
    public static WebApplication UseLocalizedValidation(this WebApplication app)
    {
        var localizer = app.Services.GetRequiredService<IStringLocalizerFactory>().Create(typeof(SharedResource));
        ValidatorOptions.Global.DisplayNameResolver = (_, member, _) =>
            member is null ? null : localizer[TextHelpers.Humanize(member.Name)].Value;
        return app;
    }
}

public static class LanguageCookie
{
    public const string Name = "crm.lang";

    public static void Write(HttpResponse response, string uiCulture) =>
        response.Cookies.Append(
            Name,
            CookieRequestCultureProvider.MakeCookieValue(new RequestCulture(LocalizationSettings.DataCulture, uiCulture)),
            new CookieOptions { Expires = DateTimeOffset.UtcNow.AddYears(1), IsEssential = true, SameSite = SameSiteMode.Lax, HttpOnly = true });
}
