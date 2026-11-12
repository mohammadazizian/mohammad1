import itertools
from lib import *
pd.set_option("display.width",250); pd.set_option("display.max_rows",500)
D={s:load(s,"5min") for s in ["BTCUSDT","ETHUSDT"]}
F={}
for s,d in D.items():
    lc=np.log(d.close); sg=lc.diff().rolling(288*7).std(); vs=d.volume/d.volume.rolling(288*7).mean()
    F[s]=(lc,sg,vs)
rows=[]
for n,zt,vt,mh,sl,tp in itertools.product([3,6,12,24],[2.5,3,4,5],[0,2],[6,12,36,96],[0,6],[0]):
    r=dict(n=n,z=zt,v=vt,mh=mh,sl=sl)
    for s,d in D.items():
        lc,sg,vs=F[s]
        z=(lc-lc.shift(n))/(sg*np.sqrt(n))
        sig=((z<-zt)&(vs.rolling(n).mean()>vt)).astype(int)
        st=stats(bt(d,sig.values,sl=sl,tp=tp,maxhold=mh,atr_n=288))
        for k,v in st.items(): r[s[:3]+"_"+k]=v
    rows.append(r)
df=pd.DataFrame(rows); df["score"]=df[["BTC_pos","ETH_pos"]].min(axis=1); df["tot"]=df.BTC_tot+df.ETH_tot
print(df.sort_values(["score","tot"],ascending=False).head(40).to_string(index=False))
