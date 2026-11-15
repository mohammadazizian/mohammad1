using System.Text.RegularExpressions;
using Crm.Application.Common.Exceptions;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Options;

namespace Crm.Infrastructure.Files;

public sealed class FileStorageOptions
{
    public const string SectionName = "Storage";

    /// <summary>Upload folder; relative paths are resolved against the content root.</summary>
    public string Path { get; set; } = "App_Data/uploads";
    public long MaxFileBytes { get; set; } = 10 * 1024 * 1024;
    public string[] BlockedExtensions { get; set; } = [".exe", ".dll", ".bat", ".cmd", ".com", ".msi", ".ps1", ".sh", ".scr", ".js", ".vbs"];
}

/// <summary>Stores uploads on the local disk (a Docker volume in production) under random names.</summary>
public sealed partial class LocalFileStorage : IFileStorage
{
    private readonly FileStorageOptions _options;
    private readonly string _root;

    public LocalFileStorage(IOptions<FileStorageOptions> options, IHostEnvironment environment)
    {
        _options = options.Value;
        _root = Path.GetFullPath(Path.Combine(environment.ContentRootPath, _options.Path));
        Directory.CreateDirectory(_root);
    }

    public async Task<StoredFile> SaveAsync(Stream content, string fileName, string? contentType, CancellationToken cancellationToken = default)
    {
        var safeName = Path.GetFileName(fileName);
        var extension = Path.GetExtension(safeName).ToLowerInvariant();

        if (_options.BlockedExtensions.Contains(extension) || !ExtensionPattern().IsMatch(extension))
        {
            throw new AppValidationException("File", $"Files of type '{extension}' are not allowed.");
        }

        if (content.CanSeek && content.Length > _options.MaxFileBytes)
        {
            throw new AppValidationException("File", $"'{safeName}' exceeds the limit of {_options.MaxFileBytes / (1024 * 1024)} MB.");
        }

        var storedName = $"{Guid.NewGuid():N}{extension}";
        await using var target = new FileStream(Path.Combine(_root, storedName), FileMode.CreateNew, FileAccess.Write);
        await content.CopyToAsync(target, cancellationToken);

        return new StoredFile(storedName, safeName, string.IsNullOrWhiteSpace(contentType) ? "application/octet-stream" : contentType, target.Length);
    }

    public Stream? OpenRead(string storedName)
    {
        // Only names this class generated are accepted, which rules out path traversal.
        if (!StoredNamePattern().IsMatch(storedName))
        {
            return null;
        }

        var path = Path.Combine(_root, storedName);
        return File.Exists(path) ? new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read) : null;
    }

    [GeneratedRegex(@"^[0-9a-f]{32}(\.[a-z0-9]{1,10})?$")]
    private static partial Regex StoredNamePattern();

    [GeneratedRegex(@"^(\.[a-z0-9]{1,10})?$")]
    private static partial Regex ExtensionPattern();
}
