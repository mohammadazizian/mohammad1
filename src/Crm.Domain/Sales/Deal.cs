using Crm.Domain.Common;

namespace Crm.Domain.Sales;

public class Pipeline : AuditableEntity
{
    public string Name { get; set; } = string.Empty;
    public bool IsDefault { get; set; }
    public ICollection<PipelineStage> Stages { get; } = [];
}

public class PipelineStage : AuditableEntity
{
    public Guid PipelineId { get; set; }
    public Pipeline? Pipeline { get; set; }
    public LocalizedText Name { get; set; } = new();
    public int Order { get; set; }

    /// <summary>Win probability in percent (0-100), used for weighted forecasts.</summary>
    public int Probability { get; set; }
    public bool IsWon { get; set; }
    public bool IsLost { get; set; }

    public bool IsClosed => IsWon || IsLost;
}

public class Deal : AuditableEntity, ITrackableEntity
{
    public string Title { get; set; } = string.Empty;
    public Guid CustomerId { get; set; }
    public Customer? Customer { get; set; }
    public Guid PipelineId { get; set; }
    public Pipeline? Pipeline { get; set; }
    public Guid StageId { get; private set; }
    public PipelineStage? Stage { get; private set; }
    public decimal Amount { get; set; }
    public DateTime? ExpectedCloseDate { get; set; }
    public DateTime? ClosedAt { get; private set; }
    public Guid? OwnerUserId { get; set; }
    public string? Notes { get; set; }

    public TrackableEntityType EntityType => TrackableEntityType.Deal;
    public string DisplayName => Title;

    /// <summary>Moves the deal to another stage of its own pipeline (Kanban drag &amp; drop).</summary>
    public void MoveTo(PipelineStage stage, DateTime utcNow)
    {
        if (stage.PipelineId != PipelineId)
        {
            throw new DomainException("The target stage belongs to a different pipeline.");
        }

        if (stage.Id == StageId)
        {
            return;
        }

        var previousStageId = StageId;
        StageId = stage.Id;
        Stage = stage;
        ClosedAt = stage.IsClosed ? utcNow : null;

        if (previousStageId != Guid.Empty)
        {
            AddDomainEvent(new DealStageChangedEvent(Id, previousStageId, stage.Id, stage.Name.En));
        }
    }
}

public sealed record DealStageChangedEvent(Guid DealId, Guid FromStageId, Guid ToStageId, string ToStageName) : IDomainEvent;
