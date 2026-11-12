import numpy as np, pandas as pd
from numba import njit
from lib import load, atr, START, END
COST=0.0010
def prep(sym, shift_h=0):
    d=load(sym); idx=d.index-pd.Timedelta(hours=shift_h)
    day=idx.floor("1D"); g=d.groupby(day)
    dh=g.high.max().shift(1); dl=g.low.min().shift(1)
    pdh=pd.Series(day,index=d.index).map(dh).values; pdl=pd.Series(day,index=d.index).map(dl).values
    dayid=(pd.Series(day).rank(method="dense").astype(int)).values
    sg=(np.log(d.close).diff().rolling(672).std()*np.sqrt(96)).fillna(0).values
    return dict(d=d,o=d.open.values,h=d.high.values,l=d.low.values,c=d.close.values,f=d.funding.values,pdh=pdh,pdl=pdl,day=dayid,
                a=atr(d,96).fillna(0).values,sg=sg,idx=d.index)
@njit(cache=True)
def run(o,h,l,c,f,pdh,pdl,day,a,sg,i0,i1,mode,m,stop_k,tgt,hold,maxtr,T,vt):
    """mode 0 breakout (first close beyond level), 1 sweep (pierce within last m bars, close back inside).
    stop_k: breakout -> k*ATR from entry (0 none); sweep -> extreme + stop_k*ATR.
    tgt: 0 none, 1 mid of prior range, 2 opposite level, negative -> R multiple (-tgt).
    hold: 0 = exit at first bar of next day, else bars.  T: monthly target (fraction), vt: vol target."""
    n=len(c); E=np.empty(n,np.int64);X=np.empty(n,np.int64);Dr=np.empty(n,np.int64);R=np.empty(n,np.float64);k=0
    pos=0;ep=0.;sp=0.;tp=0.;ei=0;w=0.;fd=0.;cnt=0;cd=-1;mp=0.;ment=0;cm=-1
    for i in range(i0,i1):
        if day[i]!=cd: cd=day[i];cnt=0
        mo=i  # month handled by caller via month array? use day-based reset passed in pdh? simplified below
        if pos!=0:
            xp=0.
            if i>ei:
                fd+=f[i]*pos
                if (hold==0 and day[i]!=day[ei]) or (hold>0 and i-ei>=hold) or i==i1-1: xp=o[i]
            if pos==1:
                if sp>0 and o[i]<=sp: xp=o[i]
                elif xp==0. and sp>0 and l[i]<=sp: xp=sp
                elif xp==0. and tp>0 and h[i]>=tp: xp=tp
            else:
                if sp>0 and o[i]>=sp: xp=o[i]
                elif xp==0. and sp>0 and h[i]>=sp: xp=sp
                elif xp==0. and tp>0 and l[i]<=tp: xp=tp
            if xp!=0.:
                E[k]=ei;X[k]=i;Dr[k]=pos;R[k]=w*(pos*(xp/ep-1)-0.0010-fd);k+=1;pos=0
        if pos==0 and i>i0 and i<i1-1 and cnt<maxtr and day[i]==day[i-1] and pdh[i-1]==pdh[i-1] and a[i-1]>0 and sg[i-1]>0:
            j=i-1; s=0; ext=0.
            if mode==0:
                if c[j]>pdh[j] and (j==0 or c[j-1]<=pdh[j] or day[j-1]!=day[j]): s=1
                elif c[j]<pdl[j] and (c[j-1]>=pdl[j] or day[j-1]!=day[j]): s=-1
            else:
                hi=h[j];lo=l[j]
                for q in range(1,m):
                    if j-q>=0 and day[j-q]==day[j]:
                        if h[j-q]>hi: hi=h[j-q]
                        if l[j-q]<lo: lo=l[j-q]
                if hi>pdh[j] and c[j]<pdh[j] and (c[j-1]>=pdh[j] or h[j]>pdh[j]): s=-1; ext=hi
                elif lo<pdl[j] and c[j]>pdl[j] and (c[j-1]<=pdl[j] or l[j]<pdl[j]): s=1; ext=lo
            if s!=0:
                pos=s;ep=o[i];ei=i;fd=0.;cnt+=1
                w=vt/sg[j]
                if w>1.: w=1.
                if mode==0: sp=ep-s*stop_k*a[j] if stop_k>0 else 0.
                else: sp=ext+(-s)*stop_k*a[j] if stop_k>=0 else 0.
                if mode==1 and ((s==1 and sp>=ep) or (s==-1 and sp<=ep)): sp=ep-s*0.5*a[j]
                mid=0.5*(pdh[j]+pdl[j])
                if tgt==0: tp=0.
                elif tgt==1: tp=mid
                elif tgt==2: tp=pdl[j] if s==-1 else pdh[j]
                else: tp=ep+s*(-tgt)*abs(ep-sp) if sp>0 else 0.
                if tp>0 and ((s==1 and tp<=ep) or (s==-1 and tp>=ep)): tp=0.
    return E[:k],X[:k],Dr[:k],R[:k]
def bt(P,start,end,mode,m=1,stop_k=0.,tgt=0,hold=0,maxtr=1,T=9.,vt=0.02):
    i0=P["idx"].searchsorted(start); i1=P["idx"].searchsorted(end)
    E,X,Dr,R=run(P["o"],P["h"],P["l"],P["c"],P["f"],P["pdh"],P["pdl"],P["day"],P["a"],P["sg"],i0,i1,mode,m,float(stop_k),float(tgt),hold,maxtr,T,vt)
    return pd.DataFrame({"entry":P["idx"][E],"exit":P["idx"][X],"dir":Dr,"pnl":R})
def govern(tr,T):
    if T>=9 or len(tr)==0: return tr
    tr=tr.sort_values("entry").reset_index(drop=True); keep=[]; ex=tr.exit.values; en=tr.entry.values; pn=tr.pnl.values
    mon=tr.entry.dt.tz_localize(None).dt.to_period("M").dt.start_time.dt.tz_localize("UTC").values
    kex=[];kpn=[]
    for i in range(len(tr)):
        s=0.;c=0
        for a_,b_ in zip(kex,kpn):
            if a_>=mon[i] and a_<=en[i]: s+=b_
        ments=sum(1 for q in keep if en[q]>=mon[i])
        if ments>0 and s>=T: continue
        keep.append(i);kex.append(ex[i]);kpn.append(pn[i])
    return tr.loc[keep]
def mstats(tr,a,b):
    ix=pd.period_range(a.tz_localize(None),(b-pd.Timedelta(minutes=1)).tz_localize(None),freq="M")
    if len(tr)==0: return 0,0,0.0,0.0
    m=tr.groupby(tr.exit.dt.tz_localize(None).dt.to_period("M")).pnl.sum().reindex(ix).fillna(0); c=tr.groupby(tr.entry.dt.tz_localize(None).dt.to_period("M")).size().reindex(ix).fillna(0)
    return int((m>0).sum()),int(c.min()),round(m.sum()*100,1),round(m.min()*100,1)
