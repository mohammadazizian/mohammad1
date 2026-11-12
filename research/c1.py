# Concepts 1-3 quick grid
import itertools, sys
from lib import *
def sweep_sig(d,N,wick):
    a=atr(d,96); pl=d.low.rolling(N).min().shift(1); ph=d.high.rolling(N).max().shift(1)
    L=(d.low<pl)&(d.close>pl)&((d.close-d.low)>wick*a)
    S=(d.high>ph)&(d.close<ph)&((d.high-d.close)>wick*a)
    return L.astype(int)-S.astype(int)
def donch_sig(d,N):
    ph=d.high.rolling(N).max().shift(1); pl=d.low.rolling(N).min().shift(1)
    return (d.close>ph).astype(int)-(d.close<pl).astype(int)
def mr_sig(d,n,lo,trendN):
    r=rsi(d.close,n); e=d.close.ewm(span=max(trendN,1)).mean()
    if trendN==0: return (r<lo).astype(int)-(r>100-lo).astype(int)
    return ((r<lo)&(d.close>e)).astype(int)-((r>100-lo)&(d.close<e)).astype(int)
rows=[]
D={s:load(s) for s in ["BTCUSDT","ETHUSDT"]}
def ev(name,f,**kw):
    r={"name":name}
    for s,d in D.items():
        st=stats(bt(d,f(d).values,**kw))
        for k,v in st.items(): r[s[:3]+"_"+k]=v
    rows.append(r)
for N,w,sl,tp,mh in itertools.product([48,96,288,672],[0.5,1.0,2.0],[1.0,2.0],[1.0,2.0,4.0],[96]):
    ev(f"sweep N{N} w{w} sl{sl} tp{tp}",lambda d:sweep_sig(d,N,w),sl=sl,tp=tp,maxhold=mh)
for N,tr in itertools.product([96,288,672,1344,2880],[3,6,10,15]):
    ev(f"donch N{N} tr{tr}",lambda d:donch_sig(d,N),trail=tr)
    ev(f"donchFade N{N} tr{tr}",lambda d:-donch_sig(d,N),sl=tr,tp=tr/2,maxhold=384)
for n,lo,tn,sl,tp in itertools.product([2,6,14],[10,20,30],[0,960],[2.,4.],[1.,2.]):
    ev(f"rsi n{n} lo{lo} tr{tn} sl{sl} tp{tp}",lambda d:mr_sig(d,n,lo,tn),sl=sl,tp=tp,maxhold=96)
df=pd.DataFrame(rows); df["score"]=df[["BTC_pos","ETH_pos"]].min(axis=1); df["tot"]=df.BTC_tot+df.ETH_tot
pd.set_option("display.width",250); pd.set_option("display.max_rows",500)
print(df.sort_values(["score","tot"],ascending=False).head(40).to_string(index=False))
print(df.groupby(df.name.str.split().str[0])[["BTC_tot","ETH_tot","BTC_pos","ETH_pos"]].agg(["mean","max"]).round(1))
