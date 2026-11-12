import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from strategy import *
from dataclasses import replace
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
D={s:load(s,"15min","/home/user/mohammad1/data") for s in ["BTCUSDT","ETHUSDT"]}
def ev(p):
    r={}
    for s,d in D.items():
        sm=summary(backtest(d,p))
        for k in ["trades","months_pos","min_trades_month","total_pct","worst_month","max_dd_pct","profit_factor"]: r[s[:3]+"_"+k[:9]]=sm[k]
    return r
if __name__=="__main__":
    rows=[]
    for st,T,L,vt,sl in itertools.product([0,1.5,2.5,4],[0.02,0.03,0.05,1],[0.06,0.1,1],[0.01,0.02],["ADB","AD","A","D"]):
        p=Params(stop_sigma=st,month_target=T*vt/0.02,month_loss=L*vt/0.02,vol_target=vt,a_on="A" in sl,d_on="D" in sl,b_on="B" in sl)
        rows.append(dict(stop=st,T=T,L=L,vt=vt,sl=sl,**ev(p)))
    df=pd.DataFrame(rows); df["mp"]=df[["BTC_months_po","ETH_months_po"]].min(axis=1); df["tot"]=df.BTC_total_pct+df.ETH_total_pct
    df.to_pickle("/home/user/mohammad1/research/g1.pkl")
    print(df.sort_values(["mp","tot"],ascending=False).head(40).to_string(index=False))
