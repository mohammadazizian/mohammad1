import itertools, numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
import mm, bot6 as B, strategy2 as S2, strategy3 as S3
from mm import *
T=lambda s: pd.Timestamp(s,tz='UTC')
_orig=B.load; _IDX=_orig('BTCUSDT').index
def _load(sym,path='data'):
    return _orig(sym,path).reindex(_IDX).ffill()      # same 15m index for every coin; bars before listing stay NaN (no signals)
B.load=_load
def go(tag,streams,sl,tp,start,end,strict=True,**kw):
    k=dict(lev_cap=3.0,compound=True,rmult=RMULT,risk=0.005,month_loss=0.07)
    if strict: k.update(vol_max=0.8,trend_sleeves=("Sx","Fx"))
    k.update(kw)
    tr,eq=run(streams,sl,tp,start=start,end=end,**k); st=account_stats(tr,eq,start,end)
    me=eq.resample("ME").last(); mr=me.pct_change(); mr.iloc[0]=me.iloc[0]-1
    cnt=tr.groupby(tr.entry.dt.tz_localize(None).dt.to_period("M")).size() if len(tr) else pd.Series(dtype=int)
    act=mr[[ (d.tz_localize(None).to_period('M') in cnt.index) for d in mr.index]]
    print(f"{tag:46s} x{st['final']:6.2f} CAGR {st['cagr']:6.1f}% DD {st['max_dd']:5.1f}% worst {st['worst_month']:6.1f}% months+ {int((mr>0).sum())}/{len(mr)} (active {int((act>0).sum())}/{len(act)}) win {(tr.pnl>0).mean()*100 if len(tr) else 0:4.1f}% n {len(tr)} | {st['by_year']}",flush=True)
    return tr,mr
print('=== 1. reproduce on the tuning window 2022-11-12 -> 2026-11-12')
A,Bn=T('2022-11-12'),T('2026-11-12')
go('strict S2x+S3x (reported x8.95, CAGR 73%)',S2X_STREAMS+S3X_STREAMS,SL,TP,A,Bn)
go('plain S2+S3 fixed stops (reported x7.41)',S2_STREAMS+S3_STREAMS,SL,TP,A,Bn,strict=False,month_loss=0.0)
print('=== 2. UNTOUCHED EARLIER PERIOD 2020-11-12 -> 2022-11-12 (same rules, same stops)')
C=T('2020-11-12')
go('strict S2x+S3x',S2X_STREAMS+S3X_STREAMS,SL,TP,C,A)
go('strict S2x only',S2X_STREAMS,SL,TP,C,A)
go('plain S2+S3 fixed stops',S2_STREAMS+S3_STREAMS,SL,TP,C,A,strict=False,month_loss=0.0)
go('strict, cost 0.14%',S2X_STREAMS+S3X_STREAMS,SL,TP,C,A,cost=0.0014)
go('strict, risk 1%',S2X_STREAMS+S3X_STREAMS,SL,TP,C,A,risk=0.01)
print('--- original governor versions (strategy2.py / strategy3.py) on 2020-11-12 -> 2022-11-12')
for nm,Mo in (('S2',S2),('S3',S3)):
    for s in ['BTCUSDT','ETHUSDT']:
        d=Mo.load(s,'15min'); sm=Mo.summary(Mo.backtest(d,Mo.Params(),C,A),C,A)
        print(f"   {nm} {s}: months+ {sm['months_pos']}/{sm['months']} total {sm['total_pct']:+.1f}% worst {sm['worst_month']} DD {sm['max_dd_pct']} PF {sm['profit_factor']} n {sm['trades']}")
print('=== 3. COINS NEVER USED FOR TUNING, 2022-11-12 -> 2026-11-12 (stops scaled by each coin volatility relative to BTC)')
def volratio(sym):
    f=lambda s: np.log(B.load(s).close).diff().rolling(672).std().median()
    return f(sym)/f('BTCUSDT')
new=['BNBUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','AVAXUSDT','LINKUSDT','DOTUSDT']
SL2=dict(SL); TP2=dict(TP)
for c in new+['SOLUSDT']:
    r=volratio(c)
    for sv,(s0,t0) in {'Sx':(0.010,0.040),'Fx':(0.010,0.040),'Wx':(0.0075,0.045)}.items():
        if (c,sv) not in SL2: SL2[(c,sv)]=round(s0*r,4); TP2[(c,sv)]=round(t0*r,4)
    print(f'   {c} vol ratio {r:.2f} stop {SL2[(c,"Sx")]*100:.2f}%')
for c in new+['SOLUSDT']:
    go(f'{c} strict S2x+S3x own account',[(c,'Sx'),(c,'Fx'),(c,'Wx')],SL2,TP2,A,Bn)
go('7 new coins, one account',[(c,s) for c in new for s in ('Sx','Fx','Wx')],SL2,TP2,A,Bn)
go('7 new coins, S2x only',[(c,s) for c in new for s in ('Sx','Fx')],SL2,TP2,A,Bn)
go('BTC+ETH strict S2x+S3x(BTC,ETH) for comparison',S2X_STREAMS+[("BTCUSDT","Wx"),("ETHUSDT","Wx")],SL,TP,A,Bn)
