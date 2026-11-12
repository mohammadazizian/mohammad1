"""Previous-day high/low with LIMIT entries on 5m bars.
variant 0 = fade   : resting limit SELL at PDH + off, BUY at PDL - off (filled only if price trades THROUGH the limit).
variant 1 = retest : after a 5m close beyond the level, resting limit in the breakout direction back at the level.
Fees: maker 0.02% on limit fills (entry, target), taker 0.04% + 0.01% slippage on stop and time exits. Funding included.
Conservative intrabar rules: stop is checked on the fill bar itself, target only from the next bar, stop beats target."""
import numpy as np, pandas as pd, itertools
from numba import njit
from lib import load, START, END
MK=0.0002; TK=0.0005
def prep(sym, shift_h=0):
    d=load(sym,"5min"); day=(d.index-pd.Timedelta(hours=shift_h)).floor("1D"); g=d.groupby(day)
    dh=g.high.max().shift(1); dl=g.low.min().shift(1); ds=pd.Series(day,index=d.index)
    sg=(np.log(d.close).diff().rolling(288*7).std()*np.sqrt(288)).fillna(0).values
    return dict(o=d.open.values,h=d.high.values,l=d.low.values,c=d.close.values,f=d.funding.values,pdh=ds.map(dh).values,pdl=ds.map(dl).values,
                day=ds.rank(method="dense").astype(int).values,sg=sg,idx=d.index)
@njit(cache=True)
def run(o,h,l,c,f,pdh,pdl,day,sg,i0,i1,variant,off,stop,tgt,hold,buf,vt):
    """off/stop in daily-sigma units of price. tgt: 1 mid, 2 opposite level, <0 R multiple, 0 none. hold: 0 = until day end, else bars."""
    n=len(c); E=np.empty(n,np.int64);X=np.empty(n,np.int64);Dr=np.empty(n,np.int64);R=np.empty(n,np.float64);K=np.empty(n,np.int64);k=0
    pos=0;ep=0.;sp=0.;tp=0.;ei=0;w=0.;fd=0.;cd=-1
    usedH=False;usedL=False;armH=False;armL=False;LH=0.;LL=0.;sgd=0.
    for i in range(i0,i1):
        if day[i]!=cd:
            cd=day[i];usedH=False;usedL=False;armH=(variant==0);armL=(variant==0)
            sgd=sg[i-1]; LH=pdh[i]; LL=pdl[i]
        if LH!=LH or sgd<=0: continue
        if pos!=0:
            xp=0.;kind=0
            fd+=f[i]*pos
            if (hold==0 and day[i]!=day[ei]) or (hold>0 and i-ei>=hold) or i==i1-1: xp=o[i];kind=3
            if pos==1:
                if o[i]<=sp: xp=o[i];kind=2
                elif xp==0. and l[i]<=sp: xp=sp;kind=2
                elif xp==0. and tp>0 and h[i]>tp*(1+buf): xp=tp;kind=1
            else:
                if o[i]>=sp: xp=o[i];kind=2
                elif xp==0. and h[i]>=sp: xp=sp;kind=2
                elif xp==0. and tp>0 and l[i]<tp*(1-buf): xp=tp;kind=1
            if xp!=0.:
                cost=MK+(MK if kind==1 else TK)
                E[k]=ei;X[k]=i;Dr[k]=pos;K[k]=kind;R[k]=w*(pos*(xp/ep-1)-cost-fd);k+=1;pos=0
            continue
        if i>=i1-1: continue
        # resting limit orders (levels known from the previous day; no look-ahead)
        s=0;px=0.
        if variant==0:
            ph=LH*(1+off*sgd); pl=LL*(1-off*sgd)
            if armH and not usedH and o[i]<ph and h[i]>ph*(1+buf): s=-1;px=ph;usedH=True
            elif armL and not usedL and o[i]>pl and l[i]<pl*(1-buf): s=1;px=pl;usedL=True
        else:
            if armH and not usedH and o[i]>LH and l[i]<LH*(1-buf): s=1;px=LH;usedH=True
            elif armL and not usedL and o[i]<LL and h[i]>LL*(1+buf): s=-1;px=LL;usedL=True
            if s==0:
                if c[i]>LH*(1+off*sgd): armH=True
                if c[i]<LL*(1-off*sgd): armL=True
        if s!=0:
            pos=s;ep=px;ei=i;fd=0.
            w=vt/sgd
            if w>1.: w=1.
            sp=ep*(1-s*stop*sgd)
            mid=0.5*(LH+LL)
            if tgt==0: tp=0.
            elif tgt==1: tp=mid
            elif tgt==2: tp=(LL if s==-1 else LH)
            else: tp=ep*(1+s*(-tgt)*stop*sgd)
            if variant==1 and tgt>0: tp=ep*(1+s*tgt*stop*sgd)     # retest: targets are R multiples only
            if tp>0 and ((s==1 and tp<=ep) or (s==-1 and tp>=ep)): tp=0.
            # stop hit on the fill bar itself (conservative)
            if (s==1 and l[i]<=sp) or (s==-1 and h[i]>=sp):
                E[k]=ei;X[k]=i;Dr[k]=pos;K[k]=2;R[k]=w*(pos*(sp/ep-1)-MK-TK);k+=1;pos=0
    return E[:k],X[:k],Dr[:k],R[:k],K[:k]
def bt(P,a,b,variant,off=0.,stop=0.3,tgt=1,hold=0,buf=0.0001,vt=0.02):
    i0=P["idx"].searchsorted(a); i1=P["idx"].searchsorted(b)
    E,X,Dr,R,K=run(P["o"],P["h"],P["l"],P["c"],P["f"],P["pdh"],P["pdl"],P["day"],P["sg"],i0,i1,variant,float(off),float(stop),float(tgt),hold,buf,vt)
    return pd.DataFrame({"entry":P["idx"][E],"exit":P["idx"][X],"dir":Dr,"pnl":R,"kind":K})
P0=pd.Timestamp("2022-11-12",tz="UTC"); MID=START
if __name__=="__main__":
    pd.set_option("display.width",280); pd.set_option("display.max_rows",400)
    cfgs=[dict(variant=0,off=o_,stop=s_,tgt=t_,hold=H) for o_ in [0,0.1,0.25] for s_ in [0.15,0.3,0.6,1.0] for t_ in [1,2,-1,-2,0] for H in [0,48]]
    cfgs+=[dict(variant=1,off=o_,stop=s_,tgt=t_,hold=H) for o_ in [0,0.1,0.25] for s_ in [0.15,0.3,0.6] for t_ in [1,2,3,0] for H in [0,48,144]]
    for sh in [0,13]:
        PP={s:prep(s,sh) for s in ["BTCUSDT","ETHUSDT"]}; rows=[]
        for cf in cfgs:
            r=dict(cf)
            for s,P in PP.items():
                for tag,(a,b) in {"p1":(P0,MID),"p2":(MID,END)}.items():
                    tr=bt(P,a,b,**cf); r[f"{s[:3]}_{tag}"]=round(tr.pnl.sum()*100,1)
                    if s=="BTCUSDT" and tag=="p2": r["n"]=len(tr); r["wr"]=round((tr.pnl>0).mean()*100)
            rows.append(r)
        df=pd.DataFrame(rows); c4=["BTC_p1","BTC_p2","ETH_p1","ETH_p2"]; df["min4"]=df[c4].min(axis=1); df["sum4"]=df[c4].sum(axis=1)
        df.to_pickle(f"pd_limit_{sh}.pkl")
        print(f"=== day starts {sh:02d}:00 UTC: {len(df)} configs, all-4-positive {(df.min4>0).sum()} | mean cell by variant:",df.groupby("variant")[c4].mean().round(1).to_dict("index"))
        print(df.sort_values("min4",ascending=False).head(14).to_string(index=False))
