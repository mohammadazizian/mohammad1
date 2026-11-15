using Crm.Application.Common.Behaviors;
using Crm.Domain.Collaboration;
using Crm.Domain.Sales;

namespace Crm.Application.Features.Deals;

public sealed record DealCardDto(Guid Id, string Title, string CustomerName, decimal Amount, DateTime? ExpectedCloseDate);

public sealed record DealColumnDto(Guid StageId, LocalizedText Name, int Probability, bool IsWon, bool IsLost, IReadOnlyList<DealCardDto> Deals)
{
    public decimal Total => Deals.Sum(d => d.Amount);
}

public sealed record DealBoardDto(Guid PipelineId, string PipelineName, IReadOnlyList<DealColumnDto> Columns);

/// <summary>Kanban board of the default (or given) pipeline.</summary>
public sealed record GetDealBoardQuery(Guid? PipelineId = null) : IRequest<DealBoardDto>;

internal sealed class GetDealBoardQueryHandler(IApplicationDbContext db) : IRequestHandler<GetDealBoardQuery, DealBoardDto>
{
    public async Task<DealBoardDto> Handle(GetDealBoardQuery request, CancellationToken cancellationToken)
    {
        var pipeline = await db.Pipelines.AsNoTracking()
            .Include(p => p.Stages)
            .Where(p => request.PipelineId == null ? p.IsDefault : p.Id == request.PipelineId)
            .FirstOrDefaultAsync(cancellationToken)
            ?? throw new NotFoundException(nameof(Pipeline), request.PipelineId?.ToString() ?? "default");

        var deals = await db.Deals.AsNoTracking()
            .Where(d => d.PipelineId == pipeline.Id)
            .OrderByDescending(d => d.Amount)
            .Select(d => new { d.StageId, Card = new DealCardDto(d.Id, d.Title, d.Customer!.Name, d.Amount, d.ExpectedCloseDate) })
            .ToListAsync(cancellationToken);

        var columns = pipeline.Stages.OrderBy(s => s.Order)
            .Select(s => new DealColumnDto(
                s.Id, s.Name, s.Probability, s.IsWon, s.IsLost,
                deals.Where(d => d.StageId == s.Id).Select(d => d.Card).ToList()))
            .ToList();

        return new DealBoardDto(pipeline.Id, pipeline.Name, columns);
    }
}

public sealed record DealDto(
    Guid Id,
    string Title,
    Guid CustomerId,
    string CustomerName,
    Guid PipelineId,
    Guid StageId,
    LocalizedText StageName,
    bool IsWon,
    bool IsLost,
    decimal Amount,
    DateTime? ExpectedCloseDate,
    DateTime? ClosedAt,
    string? Notes,
    DateTime CreatedAt);

public sealed record GetDealQuery(Guid Id) : IRequest<DealDto>;

internal sealed class GetDealQueryHandler(IApplicationDbContext db) : IRequestHandler<GetDealQuery, DealDto>
{
    public async Task<DealDto> Handle(GetDealQuery request, CancellationToken cancellationToken) =>
        await db.Deals.AsNoTracking()
            .Where(d => d.Id == request.Id)
            .Select(d => new DealDto(
                d.Id, d.Title, d.CustomerId, d.Customer!.Name, d.PipelineId, d.StageId, d.Stage!.Name,
                d.Stage.IsWon, d.Stage.IsLost, d.Amount, d.ExpectedCloseDate, d.ClosedAt, d.Notes, d.CreatedAt))
            .FirstOrDefaultAsync(cancellationToken)
        ?? throw new NotFoundException(nameof(Deal), request.Id);
}

public sealed record StageOptionDto(Guid Id, LocalizedText Name);

public sealed record GetStageOptionsQuery : IRequest<IReadOnlyList<StageOptionDto>>;

internal sealed class GetStageOptionsQueryHandler(IApplicationDbContext db)
    : IRequestHandler<GetStageOptionsQuery, IReadOnlyList<StageOptionDto>>
{
    public async Task<IReadOnlyList<StageOptionDto>> Handle(GetStageOptionsQuery request, CancellationToken cancellationToken) =>
        await db.PipelineStages.AsNoTracking()
            .Where(s => s.Pipeline!.IsDefault)
            .OrderBy(s => s.Order)
            .Select(s => new StageOptionDto(s.Id, s.Name))
            .ToListAsync(cancellationToken);
}

public sealed class UpsertDealCommand : IRequest<Guid>
{
    public Guid? Id { get; set; }
    public string Title { get; set; } = string.Empty;
    public Guid CustomerId { get; set; }
    public Guid StageId { get; set; }
    public decimal Amount { get; set; }
    public DateTime? ExpectedCloseDate { get; set; }
    public string? Notes { get; set; }
}

internal sealed class UpsertDealCommandValidator : AbstractValidator<UpsertDealCommand>
{
    public UpsertDealCommandValidator()
    {
        RuleFor(x => x.Title).NotEmpty().MaximumLength(200);
        RuleFor(x => x.CustomerId).NotEmpty();
        RuleFor(x => x.StageId).NotEmpty();
        RuleFor(x => x.Amount).GreaterThanOrEqualTo(0);
        RuleFor(x => x.Notes).MaximumLength(4000);
    }
}

internal sealed class UpsertDealCommandHandler(IApplicationDbContext db, TimeProvider clock) : IRequestHandler<UpsertDealCommand, Guid>
{
    public async Task<Guid> Handle(UpsertDealCommand request, CancellationToken cancellationToken)
    {
        var stage = await db.PipelineStages.FirstOrDefaultAsync(s => s.Id == request.StageId, cancellationToken)
            ?? throw new NotFoundException(nameof(PipelineStage), request.StageId);

        if (!await db.Customers.AnyAsync(c => c.Id == request.CustomerId, cancellationToken))
        {
            throw new NotFoundException(nameof(Customer), request.CustomerId);
        }

        Deal deal;
        if (request.Id is { } id)
        {
            deal = await db.Deals.FirstOrDefaultAsync(d => d.Id == id, cancellationToken)
                ?? throw new NotFoundException(nameof(Deal), id);
        }
        else
        {
            deal = new Deal { PipelineId = stage.PipelineId };
            db.Deals.Add(deal);
        }

        deal.Title = request.Title.Trim();
        deal.CustomerId = request.CustomerId;
        deal.Amount = request.Amount;
        deal.ExpectedCloseDate = request.ExpectedCloseDate;
        deal.Notes = request.Notes;
        deal.MoveTo(stage, clock.GetUtcNow().UtcDateTime);

        await db.SaveChangesAsync(cancellationToken);
        return deal.Id;
    }
}

public sealed record MoveDealCommand(Guid DealId, Guid StageId) : IRequest;

internal sealed class MoveDealCommandHandler(IApplicationDbContext db, TimeProvider clock) : IRequestHandler<MoveDealCommand>
{
    public async Task Handle(MoveDealCommand request, CancellationToken cancellationToken)
    {
        var deal = await db.Deals.FirstOrDefaultAsync(d => d.Id == request.DealId, cancellationToken)
            ?? throw new NotFoundException(nameof(Deal), request.DealId);
        var stage = await db.PipelineStages.FirstOrDefaultAsync(s => s.Id == request.StageId, cancellationToken)
            ?? throw new NotFoundException(nameof(PipelineStage), request.StageId);

        deal.MoveTo(stage, clock.GetUtcNow().UtcDateTime);
        await db.SaveChangesAsync(cancellationToken);
    }
}

public sealed record DeleteDealCommand(Guid Id) : IRequest;

internal sealed class DeleteDealCommandHandler(IApplicationDbContext db) : IRequestHandler<DeleteDealCommand>
{
    public async Task Handle(DeleteDealCommand request, CancellationToken cancellationToken)
    {
        var deal = await db.Deals.FirstOrDefaultAsync(d => d.Id == request.Id, cancellationToken)
            ?? throw new NotFoundException(nameof(Deal), request.Id);
        db.Deals.Remove(deal);
        await db.SaveChangesAsync(cancellationToken);
    }
}

/// <summary>Writes the stage change to the deal's activity timeline.</summary>
internal sealed class DealStageChangedEventHandler(IApplicationDbContext db)
    : INotificationHandler<DomainEventNotification<DealStageChangedEvent>>
{
    public async Task Handle(DomainEventNotification<DealStageChangedEvent> notification, CancellationToken cancellationToken)
    {
        var domainEvent = notification.Event;
        var title = await db.Deals.AsNoTracking()
            .Where(d => d.Id == domainEvent.DealId)
            .Select(d => d.Title)
            .FirstOrDefaultAsync(cancellationToken);
        if (title is null)
        {
            return;
        }

        db.ActivityLogs.Add(ActivityLog.For(
            new EntityRef(TrackableEntityType.Deal, domainEvent.DealId), title, ActivityAction.StageChanged, domainEvent.ToStageName));
        await db.SaveChangesAsync(cancellationToken);
    }
}
