import sys; sys.path.insert(0,"/home/user/mohammad1")
from mm import *
pd.set_option("display.width",250)
ALL=S2_STREAMS+S3_STREAMS
def R(tag,**kw):
    tr,_=run(ALL,SL,TP,risk=0.01,compound=False,rmult=RMULT,**kw); r=tr.pnl/0.01; y=r.groupby(tr.exit.dt.year).sum()
    s2=tr.stream.str[-1].isin(["S","F"])
    pre=tr.exit.dt.year<2026
    print(f"{tag:38s} n {len(tr):4d} | R/yr "+" ".join(f"{k}:{v:6.1f}" for k,v in y.items())+f" | <=2025 {r[pre].sum():6.1f} (avg {r[pre].mean():+.3f})  2026 {r[~pre].sum():6.1f} (avg {r[~pre].mean():+.3f}) | S2 2026 {r[s2&~pre].sum():5.1f} S3 2026 {r[~s2&~pre].sum():5.1f}")
print("Fixed size, risk-weighted R (S2 trade = 1R, S3 trade = 0.33R), no lock")
R("baseline")
for v in [0.9,0.8,0.75,0.7,0.6]: R(f"vol filter <= {v}",vol_max=v)
R("trend30 filter on S2",trend_sleeves=("S","F"))
R("trend30 filter on S2+S3",trend_sleeves=("S","F","W"))
for v in [0.8,0.75,0.7]: R(f"vol <= {v} + trend30 on S2",vol_max=v,trend_sleeves=("S","F"))
