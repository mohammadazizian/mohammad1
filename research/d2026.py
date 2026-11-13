import sys; sys.path.insert(0,"/home/user/mohammad1")
from mm import *
pd.set_option("display.width",250); pd.set_option("display.max_rows",200)
ALL=S2_STREAMS+S3_STREAMS
tr,_=run(ALL,SL,TP,risk=0.01,compound=False)            # fixed size, no lock: 1R = 1%
tr["R"]=tr.pnl/0.01; tr["yr"]=tr.exit.dt.year; tr["coin"]=tr.stream.str.split("-").str[0]; tr["sl_"]=tr.stream.str.split("-").str[1]
print("R by stream and year:"); print(tr.pivot_table(index="stream",columns="yr",values="R",aggfunc="sum",margins=True).round(0).to_string())
print("\ntrades by stream and year:"); print(tr.pivot_table(index="stream",columns="yr",values="R",aggfunc="size").to_string())
print("\navg R per trade by sleeve and year:"); print(tr.pivot_table(index="sl_",columns="yr",values="R",aggfunc="mean").round(3).to_string())
print("\nR by direction and year:"); print(tr.pivot_table(index=["sl_","dir"],columns="yr",values="R",aggfunc="sum").round(0).to_string())
print("\nexit mix by year (%):"); print((tr.pivot_table(index="kind",columns="yr",values="R",aggfunc="size")/tr.groupby("yr").size()*100).round(0).to_string())
print("\n2026 by quarter-month R:"); x=tr[tr.yr==2026]; print(x.groupby([x.exit.dt.month,"sl_"]).R.sum().unstack().round(0).T.to_string())
# attach regime features at entry
feats={}
for c in ["BTCUSDT","ETHUSDT","SOLUSDT"]:
    d=data(c)["d"]; lc=np.log(d.close); sg=lc.diff().rolling(672).std()
    f=pd.DataFrame(index=d.index)
    f["dvol"]=sg*np.sqrt(96)*100
    f["volrank"]=f.dvol.rolling(96*180).rank(pct=True)
    f["tr7"]=(lc-lc.shift(672))/(sg*np.sqrt(672))
    f["tr30"]=(lc-lc.shift(2880))/(sg*np.sqrt(2880))
    f["eff7"]=(lc-lc.shift(672)).abs()/lc.diff().abs().rolling(672).sum()        # efficiency ratio: 1 = straight trend, 0 = chop
    f["eff30"]=(lc-lc.shift(2880)).abs()/lc.diff().abs().rolling(2880).sum()
    f["hour"]=d.index.hour; f["dow"]=d.index.dayofweek
    f["volu"]=d.quote_volume.rolling(672).mean()/d.quote_volume.rolling(96*90).mean()
    feats[c[:-4]]=f.shift(1)                                                      # known at the signal bar
F=pd.concat([feats[c].reindex(tr.entry[tr.coin==c]).assign(i=tr.index[tr.coin==c]).set_index("i") for c in feats]).sort_index()
tr=tr.join(F); tr["al7"]=np.sign(tr.tr7)*tr.dir; tr["al30"]=np.sign(tr.tr30)*tr.dir
tr.to_pickle("/home/user/mohammad1/research/d2026.pkl")
print("\nregime averages at entry by year:"); print(tr.groupby("yr")[["dvol","volrank","eff7","eff30","volu"]].mean().round(3).to_string())
for col,bins in [("al7",None),("al30",None),("volrank",[0,.25,.5,.75,1.0]),("eff7",[0,.03,.06,.1,1]),("eff30",[0,.02,.04,.07,1])]:
    g=tr[col] if bins is None else pd.cut(tr[col],bins)
    for sl_ in ["S2","S3"]:
        t=tr[tr.sl_.isin(["S","F"])] if sl_=="S2" else tr[tr.sl_=="W"]
        print(f"\n{sl_}: total R by {col} and year  (avgR all years in last col)")
        p=t.pivot_table(index=g.loc[t.index],columns="yr",values="R",aggfunc="sum",observed=True).round(0); p["avgR"]=t.groupby(g.loc[t.index],observed=True).R.mean().round(3); p["n"]=t.groupby(g.loc[t.index],observed=True).size()
        print(p.to_string())
