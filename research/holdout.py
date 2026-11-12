import sys; sys.path.insert(0,"/home/user/mohammad1")
import strategy as S, pandas as pd
from dataclasses import replace
HS=pd.Timestamp("2022-11-12",tz="UTC"); HE=pd.Timestamp("2024-11-12",tz="UTC")
def rep(tr):
    e=tr.exit.dt.tz_localize(None).dt.to_period("M"); n=tr.entry.dt.tz_localize(None).dt.to_period("M")
    m=tr.groupby(e).pnl.sum()*100; ix=pd.period_range(m.index.min(),m.index.max(),freq="M"); m=m.reindex(ix).fillna(0)
    c=tr.groupby(n).size().reindex(ix).fillna(0)
    return f"pos {(m>0).sum()}/{len(m)} minTr {int(c.min())} tot {m.sum():.1f} worst {m.min():.1f} n {len(tr)}", m
if __name__=="__main__":
    for s in ["BTCUSDT","ETHUSDT"]:
        d=S.load(s)
        for tag,p in [("final",S.Params()),("no governor",S.Params(month_target=9)),("A only",S.Params(d_on=False,month_target=9)),("D only",S.Params(a_on=False,month_target=9))]:
            r,m=rep(S.backtest(d,p,HS,HE)); print(s,f"{tag:12s}",r)
            if tag=="final": print(m.round(1).to_string())
