using Microsoft.AspNetCore.Identity;

namespace Crm.Infrastructure.Identity;

public class ApplicationUser : IdentityUser<Guid>
{
    public string FullName { get; set; } = string.Empty;
    public bool IsActive { get; set; } = true;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class ApplicationRole : IdentityRole<Guid>
{
    public ApplicationRole()
    {
    }

    public ApplicationRole(string name, string? description = null, bool isSystem = false)
        : base(name)
    {
        Description = description;
        IsSystem = isSystem;
    }

    public string? Description { get; set; }

    /// <summary>System roles cannot be deleted.</summary>
    public bool IsSystem { get; set; }
}
