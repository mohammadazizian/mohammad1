import itertools
from lib import *
pd.set_option("display.width",250); pd.set_option("display.max_rows",300)
D={s:load(s) for s in ["BTCUSDT","ETHUSDT"]}
MID=pd.Timestamp("2024-11-12",tz="UTC"); P0=pd.Timestamp("2022-11-12",tz="UTC")
SG={s:np.log(d.close).diff().rolling(672).std() for s,d in D.items()}
rows=[]
for h,L,z,H in itertools.product(range(0,24,2),[192,288,480,672],[1.0,1.5,2.0],[96,192,288]):
    r=dict(h=h,L=L,z=z,H=H)
    for s,d in D.items():
        mv=(np.log(d.close)-np.log(d.close.shift(L)))/(SG[s]*np.sqrt(L)); t=(d.index.hour==(h-1)%24)&(d.index.minute==45)
        sig=((mv>z)&t).astype(int)-((mv<-z)&t).astype(int)
        tr=bt(d,sig.values,maxhold=H,start=P0)
        r[s[:3]+"_n"]=len(tr); r[s[:3]+"_p1"]=round(tr[tr.exit<MID].ret.sum()*100,1); r[s[:3]+"_p2"]=round(tr[tr.exit>=MID].ret.sum()*100,1)
    rows.append(r)
df=pd.DataFrame(rows); c4=["BTC_p1","BTC_p2","ETH_p1","ETH_p2"]; df["min4"]=df[c4].min(axis=1); df["sum4"]=df[c4].sum(axis=1)
df.to_pickle("c11.pkl")
print("frac all4>0:",(df.min4>0).mean().round(3),"mean of cells:",df[c4].mean().round(1).to_dict())
for k in ["h","L","z","H"]: print(df.groupby(k).agg(frac=("min4",lambda x:(x>0).mean()),sum4=("sum4","mean"),**{c:(c,"mean") for c in c4}).round(1).T.to_string())
print(df[df.BTC_n>=120].sort_values("min4",ascending=False).head(15).to_string(index=False))
