import itertools
from lib import *
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
D={s:load(s) for s in ["BTCUSDT","ETHUSDT"]}
MID=pd.Timestamp("2025-11-12",tz="UTC")
def cme(d,ref=(4,21),ent=(6,22),thr=0.0):
    dow=d.index.dayofweek; hr=d.index.hour; mn=d.index.minute
    # reference = close of last bar before ref hour ; entry signal on last bar before ent hour
    rh=(ref[1]-1)%24; eh=(ent[1]-1)%24
    fri=d.close.where((dow==ref[0])&(hr==rh)&(mn==45)).ffill()
    sg=np.log(d.close).diff().rolling(96*7).std()
    mv=(np.log(d.close)-np.log(fri))/(sg*np.sqrt(96*2))
    t=(dow==ent[0])&(hr==eh)&(mn==45)
    return -(((mv>thr)&t).astype(int)-((mv<-thr)&t).astype(int))
if __name__=="__main__":
    rows=[]
    for ref,ent,thr,mh,sl in itertools.product([(4,21),(4,16),(5,0)],[(6,12),(6,18),(6,22),(0,0),(0,6)],[0,0.5,1],[48,96,192,288,384],[0]):
        r=dict(ref=ref,ent=ent,thr=thr,mh=mh)
        for s,d in D.items():
            tr=bt(d,cme(d,ref,ent,thr).values,maxhold=mh,sl=sl)
            m,cnt=monthly(tr)
            r[s[:3]+"_n"]=len(tr); r[s[:3]+"_is"]=round(tr[tr.exit<MID].ret.sum()*100,1); r[s[:3]+"_oos"]=round(tr[tr.exit>=MID].ret.sum()*100,1)
            r[s[:3]+"_L"]=round(tr[tr.dir==1].ret.sum()*100,1); r[s[:3]+"_S"]=round(tr[tr.dir==-1].ret.sum()*100,1)
            r[s[:3]+"_pos"]=int((m>0).sum()); r[s[:3]+"_wr"]=(tr.ret>0).mean()
        rows.append(r)
    df=pd.DataFrame(rows); df["min4"]=df[["BTC_is","BTC_oos","ETH_is","ETH_oos"]].min(axis=1)
    print(df.sort_values("min4",ascending=False).head(30).to_string(index=False))
    print((df.min4>0).mean(), df[["BTC_is","BTC_oos","ETH_is","ETH_oos"]].mean())
    print(df.groupby("mh")[["BTC_is","BTC_oos","ETH_is","ETH_oos"]].mean().round(1))
    print(df.groupby("ent")[["BTC_is","BTC_oos","ETH_is","ETH_oos"]].mean().round(1))
    