"""Research: funding carry, cross-sectional momentum/reversal and daily trend on ten Binance perpetuals,
measured against an 8%-per-month target. Run from this directory: python research_alt_strategies.py"""
import numpy as np, pandas as pd, itertools, warnings, io, zipfile, urllib.request, os, pickle
import strategy_v2 as V
warnings.filterwarnings('ignore')
COINS=[s[:-4] for s in V.TOP10]
RAW={k:V.load(k+'USDT') for k in COINS}
def spot(sym):
    p=os.path.join(V.CACHE,f'spotd_{sym}.pkl')
    if os.path.exists(p): return pd.read_pickle(p)
    rows=[]
    for m in pd.period_range('2021-12','2026-10',freq='M'):
        try: raw=urllib.request.urlopen(f'https://data.binance.vision/data/spot/monthly/klines/{sym}/1d/{sym}-1d-{m}.zip',timeout=60).read()
        except Exception: continue
        z=zipfile.ZipFile(io.BytesIO(raw))
        for ln in z.read(z.namelist()[0]).decode().strip().splitlines():
            a=ln.split(',')
            if a[0].isdigit():
                t=int(a[0]); t=t//1000 if t>1e14 else t; rows.append((t,float(a[1]),float(a[4])))
    df=pd.DataFrame(rows,columns=['t','open','close']); df['t']=pd.to_datetime(df.t,unit='ms',utc=True); df=df.drop_duplicates('t').set_index('t').sort_index(); df.to_pickle(p); return df
# daily perp open (00:00 UTC), daily funding sum, spot open
PO=pd.DataFrame({k:RAW[k][0].open.resample('1D').first() for k in COINS})
FD=pd.DataFrame({k:RAW[k][1].resample('1D').sum() for k in COINS}).reindex(PO.index).fillna(0)
SO=pd.DataFrame({k:spot(k+'USDT').open for k in COINS}).reindex(PO.index)
RET=PO.pct_change().shift(-1)        # return from day t open to day t+1 open (known decisions at t open use data < t)
def months(daily):
    p=daily.copy(); p.index=p.index.tz_localize(None); m=p.resample('ME').sum(); m.index=m.index.to_period('M'); return m['2022-01':'2026-10']*100
def stat(tag,daily,show=True):
    m=months(daily); sh=m.mean()/m.std()*np.sqrt(12); y=m.groupby(m.index.year).sum().round(0).astype(int).tolist()
    cum=m.cumsum(); dd=(cum-np.maximum(cum.cummax(),0)).min()
    L=8/np.median(m) if np.median(m)>0 else np.nan
    if show: print(f"{tag:44s} months+ {100*(m>0).mean():3.0f}% mean {m.mean():+5.2f}%/mo median {np.median(m):+5.2f} Sharpe {sh:4.2f} worst {m.min():6.1f} DD {dd:6.1f} yrs{y} | leverage for median 8%: {L:5.1f}x -> worst month {m.min()*L:7.0f}% DD {dd*L:7.0f}%")
    return m
OUT={}
print('funding per year (sum of rates, %):'); print((FD.groupby(FD.index.year).sum()*100).round(1).loc[2022:2026].to_string())
# A. funding carry: long spot / short perp while trailing 7d funding > thr; costs per switch: spot 0.10% + perp 0.04% + slip 0.02% each leg-side
basis=(PO/SO-1)
for thr in [0.0,0.00005]:
    tot=0
    for k in COINS:
        f7=FD[k].rolling(7).mean().shift(1); on=(f7>thr/1*3).astype(float)   # daily funding = 3 prints
        pnl=on*FD[k] - on*(basis[k].shift(-1)-basis[k]).fillna(0) - on.diff().abs().fillna(0)*0.0016
        tot=tot+pnl/len(COINS)
        if k in('BTC','ETH'): stat(f'carry {k} thr{thr*1e4:g}bp/8h',pnl)
    OUT[f'carry{thr}']=stat(f'carry 10 coins equal thr{thr*1e4:g}bp/8h',tot)
# top-k carry
f7=FD.rolling(7).mean().shift(1)
for kk in [2,3]:
    w=pd.DataFrame(0.0,index=PO.index,columns=COINS); cur=None
    for d in PO.index:
        if d.dayofweek==0 or cur is None:
            r=f7.loc[d].dropna(); cur=[c for c in r.sort_values(ascending=False).index[:kk] if r[c]>0.00015]
        for c in cur: w.loc[d,c]=1.0/kk
    pnl=(w*FD).sum(axis=1)-(w*(basis.shift(-1)-basis).fillna(0)).sum(axis=1)-w.diff().abs().sum(axis=1).fillna(0)*0.0016
    OUT[f'carrytop{kk}']=stat(f'carry top-{kk} by trailing funding (weekly)',pnl)
# B. cross-sectional long-short, daily rebalance, top3/bottom3, cost 0.06%/side on turnover, funding included
for h,sign in itertools.product([1,3,7,14,28],[1,-1]):
    sig=(PO/PO.shift(h)-1)*sign
    rk=sig.rank(axis=1,ascending=False); w=((rk<=3).astype(float)-(rk>=8).astype(float))/3.0
    w[sig.isna().any(axis=1)]=0
    pnl=(w*RET).sum(axis=1)-(w*FD).sum(axis=1)-w.diff().abs().sum(axis=1).fillna(0)*0.0006
    OUT[f'xs{h}_{sign}']=stat(f"cross-section {'momentum' if sign==1 else 'reversal'} {h}d (gross 2x)",pnl)
# C. daily time-series trend, each coin long above / short below SMA(N); equal weight
for N in [10,20,50,100]:
    sma=PO.rolling(N).mean(); w=np.sign(PO-sma).shift(0)/len(COINS)
    pnl=(w*RET).sum(axis=1)-(w*FD).sum(axis=1)-w.diff().abs().sum(axis=1).fillna(0)*0.0006
    OUT[f'trend{N}']=stat(f'trend SMA{N}d long/short 10 coins (gross 1x)',pnl)
    for k in ('BTC','ETH'):
        wk=np.sign(PO[k]-sma[k]); stat(f'   trend SMA{N}d {k} only',wk*RET[k]-wk*FD[k]-wk.diff().abs().fillna(0)*0.0006)

