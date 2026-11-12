import itertools
from lib import *
from c6 import cme
from c7 import shock
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
def dfade(d,h=19,L=32,thr=0.5):
    sg=np.log(d.close).diff().rolling(96*7).std()
    mv=(np.log(d.close)-np.log(d.close.shift(L)))/(sg*np.sqrt(L))
    t=(d.index.hour==(h-1)%24)&(d.index.minute==45)
    return -(((mv>thr)&t).astype(int)-((mv<-thr)&t).astype(int))
def govern(tr,T,Lm=None):
    """skip trades entered after month's realized pnl >= T (or <= -Lm)."""
    tr=tr.sort_values("entry").reset_index(drop=True)
    keep=[];closed=[]  # (exit,ret)
    for i,r in tr.iterrows():
        mstart=r.entry.tz_localize(None).to_period("M").start_time.tz_localize("UTC")
        pnl=sum(x[1] for x in closed if mstart<=x[0]<=r.entry)
        if pnl>=T or (Lm is not None and pnl<=-Lm): continue
        keep.append(i); closed.append((r.exit,r.ret))
    return tr.loc[keep]
if __name__=="__main__":
    for s in ["BTCUSDT","ETHUSDT"]:
        d=load(s)
        T={"A":bt(d,cme(d,(4,21),(0,6),0).values,maxhold=240),"B":bt(d,shock(d).values,maxhold=48),
           "D19":bt(d,dfade(d,19).values,maxhold=96),"D18":bt(d,dfade(d,18).values,maxhold=96),"D20":bt(d,dfade(d,20,48).values,maxhold=96)}
        M=pd.DataFrame({k:monthly(v)[0]*100 for k,v in T.items()})
        print(s); print(M.round(1).T.to_string()); print("pos:",(M>0).sum().to_dict(),"tot:",M.sum().round(1).to_dict())
        allt=pd.concat([T["A"],T["B"],T["D19"]])
        m,c=monthly(allt); print("A+B+D19 raw pos",(m>0).sum(),"tot",round(m.sum()*100,1),"minc",c.min())
        for Tg in [0.01,0.02,0.03,0.05,0.08]:
            g=govern(allt,Tg); m,c=monthly(g)
            print(f"  gov T={Tg}: pos {(m>0).sum()} tot {m.sum()*100:.1f} worst {m.min()*100:.1f} n {len(g)} minc {c.min()}")
