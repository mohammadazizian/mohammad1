import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from mm import *
pd.set_option("display.width",250)
def go(tag,streams,sl,tp,**kw):
    k=dict(lev_cap=3.0,compound=True,rmult=RMULT,vol_max=0.8,trend_sleeves=("Sx","Fx")); k.update(kw)
    tr,eq=run(streams,sl,tp,**k); st=account_stats(tr,eq)
    me=eq.resample("ME").last(); mr=me.pct_change(); mr.iloc[0]=me.iloc[0]-1; act=mr[mr.index>="2023-03-01"]
    cnt=tr.groupby(tr.entry.dt.tz_localize(None).dt.to_period("M")).size().reindex(pd.period_range("2023-03","2026-11",freq="M")).fillna(0)
    ls=max([len(list(g)) for kk,g in itertools.groupby(act<0) if kk] or [0])
    print(f"{tag:30s} x{st['final']:6.2f} CAGR {st['cagr']:5.1f}% DD {st['max_dd']:5.1f}% worst {st['worst_month']:6.1f}% win {(tr.pnl>0).mean()*100:4.1f}% months+ {int((act>0).sum())}/{len(act)} no-trade months {int((cnt==0).sum())} lose-streak {ls} n {len(tr)} | {st['by_year']}",flush=True)
    return tr,mr
SLm=dict(SL); TPm=dict(TP); SLm.update(SL_HW); TPm.update(TP_HW)
for risk in [0.005,0.01]:
    for lock in [0.07,0.05,0.0]:
        print(f"=== risk {risk*100}% per trade | monthly loss lock {('-%d%%'%(lock*100)) if lock else 'off'}")
        go("P1 strict, original exits",S2X_STREAMS+S3X_STREAMS,SL,TP,risk=risk,month_loss=lock)
        go("P2 strict S2 only, TP = SL",S2X_STREAMS,SL_HW,TP_HW,risk=risk,month_loss=lock)
        go("P3 P2 + strict S3",S2X_STREAMS+S3X_STREAMS,SLm,TPm,risk=risk,month_loss=lock)
tr,mr=go("P1 monthly detail",S2X_STREAMS+S3X_STREAMS,SL,TP,risk=0.005,month_loss=0.07)
print("P1 monthly %:"," ".join(f"{d.strftime('%y-%m')}:{v*100:+.1f}" for d,v in mr.items() if d>=pd.Timestamp('2023-03-01',tz='UTC')))
tr,mr=go("P2 monthly detail",S2X_STREAMS,SL_HW,TP_HW,risk=0.005,month_loss=0.07)
print("P2 monthly %:"," ".join(f"{d.strftime('%y-%m')}:{v*100:+.1f}" for d,v in mr.items() if d>=pd.Timestamp('2023-03-01',tz='UTC')))
for c in [0.0014,0.0020]:
    go(f"P1 cost {c*100:.2f}%",S2X_STREAMS+S3X_STREAMS,SL,TP,risk=0.005,month_loss=0.07,cost=c)
    go(f"P2 cost {c*100:.2f}%",S2X_STREAMS,SL_HW,TP_HW,risk=0.005,month_loss=0.07,cost=c)
