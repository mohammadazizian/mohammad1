using Crm.Application.Common.Specifications;
using Crm.Application.Features.Collaboration;
using Crm.Domain.Collaboration;
using Crm.Domain.Inventory;
using Crm.Domain.Sales;

namespace Crm.Application.Features.Dashboard;

public sealed record FunnelStageDto(LocalizedText Name, int Count, decimal Amount, bool IsWon, bool IsLost);

public sealed record LowStockDto(Guid Id, string Name, string Sku, decimal Quantity, decimal Threshold, string Unit);

public sealed record DashboardDto(
    int CustomerCount,
    int NewLeadCount,
    int OpenDealCount,
    decimal OpenDealAmount,
    decimal WeightedForecast,
    decimal WonThisMonth,
    int OpenTaskCount,
    int OverdueTaskCount,
    int LowStockCount,
    IReadOnlyList<FunnelStageDto> Funnel,
    IReadOnlyList<LowStockDto> LowStock,
    IReadOnlyList<TaskDto> MyTasks,
    IReadOnlyList<ActivityDto> RecentActivity);

public sealed record GetDashboardQuery : IRequest<DashboardDto>;

internal sealed class GetDashboardQueryHandler(
    IApplicationDbContext db,
    IReadRepository<Product> products,
    ISender sender,
    TimeProvider clock)
    : IRequestHandler<GetDashboardQuery, DashboardDto>
{
    private const int LowStockPreview = 5;

    public async Task<DashboardDto> Handle(GetDashboardQuery request, CancellationToken cancellationToken)
    {
        var now = clock.GetUtcNow().UtcDateTime;
        var monthStart = new DateTime(now.Year, now.Month, 1, 0, 0, 0, DateTimeKind.Utc);

        var stages = await db.PipelineStages.AsNoTracking()
            .Where(s => s.Pipeline!.IsDefault)
            .OrderBy(s => s.Order)
            .Select(s => new
            {
                s.Name,
                s.Probability,
                s.IsWon,
                s.IsLost,
                Count = db.Deals.Count(d => d.StageId == s.Id),
                Amount = db.Deals.Where(d => d.StageId == s.Id).Sum(d => d.Amount),
            })
            .ToListAsync(cancellationToken);

        var openStages = stages.Where(s => !s.IsWon && !s.IsLost).ToList();
        var lowStockSpecification = new LowStockProductsSpecification();
        var lowStock = await products.ListAsync(new LowStockProductsSpecification(LowStockPreview), cancellationToken);

        return new DashboardDto(
            CustomerCount: await db.Customers.CountAsync(cancellationToken),
            NewLeadCount: await db.Leads.CountAsync(l => l.Status == LeadStatus.New || l.Status == LeadStatus.Contacted, cancellationToken),
            OpenDealCount: openStages.Sum(s => s.Count),
            OpenDealAmount: openStages.Sum(s => s.Amount),
            WeightedForecast: openStages.Sum(s => s.Amount * s.Probability / 100m),
            WonThisMonth: await db.Deals.Where(d => d.Stage!.IsWon && d.ClosedAt >= monthStart).SumAsync(d => d.Amount, cancellationToken),
            OpenTaskCount: await db.Tasks.CountAsync(t => t.Status == TaskItemStatus.Open || t.Status == TaskItemStatus.InProgress, cancellationToken),
            OverdueTaskCount: await db.Tasks.CountAsync(
                t => (t.Status == TaskItemStatus.Open || t.Status == TaskItemStatus.InProgress) && t.DueAt < now, cancellationToken),
            LowStockCount: await products.CountAsync(lowStockSpecification, cancellationToken),
            Funnel: stages.Select(s => new FunnelStageDto(s.Name, s.Count, s.Amount, s.IsWon, s.IsLost)).ToList(),
            LowStock: lowStock
                .Select(p => new LowStockDto(p.Id, p.Name, p.Sku, p.StockLevels.Sum(s => s.Quantity), p.LowStockThreshold, p.Unit))
                .ToList(),
            MyTasks: await sender.Send(new GetMyPendingTasksQuery(), cancellationToken),
            RecentActivity: await sender.Send(new GetActivityQuery(Take: 8), cancellationToken));
    }
}
