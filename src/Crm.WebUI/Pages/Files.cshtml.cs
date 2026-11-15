using Crm.Application.Common.Interfaces;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace Crm.WebUI.Pages;

/// <summary>Downloads an uploaded file (chat attachment or form file). Always served as an attachment.</summary>
public class FilesModel(IFileStorage storage) : PageModel
{
    public IActionResult OnGet(string storedName, string? name)
    {
        var stream = storage.OpenRead(storedName);
        if (stream is null)
        {
            return NotFound();
        }

        var downloadName = string.IsNullOrWhiteSpace(name) ? storedName : Path.GetFileName(name);
        return File(stream, "application/octet-stream", downloadName);
    }
}
