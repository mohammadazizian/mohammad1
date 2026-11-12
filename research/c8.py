import itertools
from lib import *
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
D={s:load(s) for s in ["BTCUSDT","ETHUSDT"]}
MID=pd.Timestamp("2025-11-12",tz="UTC")
rows=[]
for h,L,H,thr in itertools.product(range(24),[16,32,48,96],[16,32,48,96],[0,0.5]):
    r=dict(h=h,L=L,H=H,thr=thr)
    for s,d in D.items():
        sg=np.log(d.close).diff().rolling(96*7).std()
        mv=(np.log(d.close)-np.log(d.close.shift(L)))/(sg*np.sqrt(L))
        t=(d.index.hour==(h-1)%24)&(d.index.minute==45)
        sig=-(((mv>thr)&t).astype(int)-((mv<-thr)&t).astype(int))
        tr=bt(d,sig.values,maxhold=H)
        r[s[:3]+"_is"]=tr[tr.exit<MID].ret.sum()*100; r[s[:3]+"_oos"]=tr[tr.exit>=MID].ret.sum()*100; r[s[:3]+"_n"]=len(tr)
        m,_=monthly(tr); r[s[:3]+"_pos"]=int((m>0).sum())
    rows.append(r)
df=pd.DataFrame(rows).round(1); c=["BTC_is","BTC_oos","ETH_is","ETH_oos"]
df["min4"]=df[c].min(axis=1); df["sum"]=df[c].sum(axis=1)
df.to_pickle("c8.pkl")
print(df.sort_values("min4",ascending=False).head(30).to_string(index=False))
print("frac all4>0 fade:",(df.min4>0).mean()," frac all4<0 (follow works gross?):",(df[c].max(axis=1)<0).mean())
print(df.groupby("h")[c+["sum"]].mean().round(1).T.to_string())
print(df.groupby(["L","H"])["sum"].mean().unstack().round(1))
