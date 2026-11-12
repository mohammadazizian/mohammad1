import numpy as np, pandas as pd
from numba import njit
START=pd.Timestamp("2024-11-12",tz="UTC"); END=pd.Timestamp("2026-11-12",tz="UTC")
FEE=0.0004; SLIP=0.0001
_cache={}
def load(sym,tf="15min"):
    k=(sym,tf)
    if k not in _cache:
        d=pd.read_parquet(f"/home/user/mohammad1/data/{sym}_5m.parquet")
        if tf!="5min":
            d=d.resample(tf).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum","taker_buy_base":"sum","funding":"sum"})
        _cache[k]=d
    return _cache[k]
def atr(d,n):
    c=d.close
    tr=pd.concat([d.high-d.low,(d.high-c.shift()).abs(),(d.low-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()
def rsi(c,n):
    x=c.diff(); u=x.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-x.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+u/dn)

@njit(cache=True)
def run(o,h,l,c,atr,fund,sig,sl,tp,trail,maxhold,exit_on_opp,cost,start_i):
    """sig[i] in {-1,0,1} at close of bar i -> enter at open i+1. sl/tp/trail in ATR multiples (0=off).
    Returns arrays: entry_idx, exit_idx, dir, ret (net, fraction of notional)."""
    n=len(c); E=np.empty(n,np.int64); X=np.empty(n,np.int64); D=np.empty(n,np.int64); R=np.empty(n,np.float64); k=0
    hs=(sl>0) or (trail>0)
    pos=0; ep=0.0; stop=0.0; take=0.0; best=0.0; ei=0; a=0.0; f=0.0
    for i in range(start_i,n):
        if pos!=0:
            xp=0.0
            # gap through stop at open
            if pos==1:
                if hs and o[i]<=stop: xp=o[i]
                elif hs and l[i]<=stop: xp=stop
                elif tp>0 and h[i]>=take: xp=take
            else:
                if hs and o[i]>=stop: xp=o[i]
                elif hs and h[i]>=stop: xp=stop
                elif tp>0 and l[i]<=take: xp=take
            if xp==0.0:
                f+=fund[i]*pos
                if trail>0:
                    if pos==1:
                        if h[i]>best: best=h[i]
                        ns=best-trail*a
                        if ns>stop: stop=ns
                    else:
                        if l[i]<best: best=l[i]
                        ns=best+trail*a
                        if ns<stop: stop=ns
                if (maxhold>0 and i-ei+1>=maxhold) or (exit_on_opp and sig[i]==-pos):
                    if i+1<n:
                        xp=o[i+1]; 
                        E[k]=ei;X[k]=i+1;D[k]=pos;R[k]=pos*(xp/ep-1)-cost-f;k+=1;pos=0
                    continue
            else:
                E[k]=ei;X[k]=i;D[k]=pos;R[k]=pos*(xp/ep-1)-cost-f;k+=1;pos=0
        if pos==0 and sig[i]!=0 and i+1<n and atr[i]>0:
            # entry at next open; processed from bar i+1
            pos=sig[i]; ep=o[i+1]; a=atr[i]; ei=i+1; best=ep; f=0.0
            stop=ep-pos*sl*a if sl>0 else (0.0 if pos==1 else 1e18)
            if sl==0 and trail>0: stop=ep-pos*trail*a
            take=ep+pos*tp*a
    return E[:k],X[:k],D[:k],R[:k]

def bt(d,sig,sl=0.,tp=0.,trail=0.,maxhold=0,opp=False,atr_n=96,cost=2*(FEE+SLIP)):
    a=atr(d,atr_n).values
    si=int(np.searchsorted(d.index.values,np.datetime64(START.tz_localize(None))))
    s=np.asarray(sig,dtype=np.int64).copy(); s[:si]=0
    E,X,D,R=run(d.open.values,d.high.values,d.low.values,d.close.values,a,d.funding.values,s,sl,tp,trail,maxhold,opp,cost,si)
    return pd.DataFrame({"entry":d.index[E],"exit":d.index[X],"dir":D,"ret":R})
MONTHS=pd.period_range("2024-11","2026-11",freq="M")
def monthly(tr):
    if len(tr)==0: return pd.Series(0.0,index=MONTHS),pd.Series(0,index=MONTHS)
    p=tr.exit.dt.tz_localize(None).dt.to_period("M")
    m=tr.groupby(p).ret.sum().reindex(MONTHS).fillna(0.0)
    cnt=tr.groupby(tr.entry.dt.tz_localize(None).dt.to_period("M")).size().reindex(MONTHS).fillna(0).astype(int)
    return m,cnt
def stats(tr):
    m,cnt=monthly(tr)
    return dict(n=len(tr),tot=round(tr.ret.sum()*100,1),pos=int((m>0).sum()),minc=int(cnt.min()),
                wr=round((tr.ret>0).mean()*100,1) if len(tr) else 0, worst=round(m.min()*100,1))
