using FluentValidation.Results;

namespace Crm.Application.Common.Exceptions;

public class NotFoundException(string name, object key) : Exception($"{name} ({key}) was not found.");

public class ForbiddenAccessException(string? message = null) : Exception(message ?? "Access denied.");

/// <summary>Input validation failed; <see cref="Errors"/> maps property names to messages.</summary>
public class AppValidationException : Exception
{
    public AppValidationException(IEnumerable<ValidationFailure> failures)
        : base("One or more validation failures have occurred.")
    {
        Errors = failures
            .GroupBy(f => f.PropertyName, f => f.ErrorMessage)
            .ToDictionary(g => g.Key, g => g.Distinct().ToArray());
    }

    public AppValidationException(string property, string message)
        : this([new ValidationFailure(property, message)])
    {
    }

    public IReadOnlyDictionary<string, string[]> Errors { get; }
}
