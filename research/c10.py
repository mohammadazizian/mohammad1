import itertools
from lib import *
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
def ld(s):
    d=pd.read_parquet(f"/home/user/mohammad1/data/{s}_5m.parquet")
    return d.resample("15min").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum","quote_volume":"sum","trades":"sum","taker_buy_base":"sum","funding":"sum"})
D={s:ld(s) for s in ["BTCUSDT","ETHUSDT"]}
OTH={"BTCUSDT":"ETHUSDT","ETHUSDT":"BTCUSDT"}
MID=pd.Timestamp("2024-11-12",tz="UTC"); P0=pd.Timestamp("2022-11-12",tz="UTC")
SG={s:np.log(d.close).diff().rolling(672).std() for s,d in D.items()}
fam={}
def reg(name,fn,exits): fam[name]=(fn,exits)
EX=[dict(maxhold=m,sl=s) for m in [16,48,96,288] for s in [0,4]]
first=lambda s: s.where(s!=s.shift(1),0)
# 1 squeeze breakout
for n,q,N in itertools.product([96,288],[0.1,0.25],[20,48,96]):
    def fn(s,d,n=n,q=q,N=N):
        bw=d.close.rolling(n).std()/d.close; lowv=bw.shift(1)<bw.rolling(96*14).quantile(q).shift(1)
        up=d.close>d.high.rolling(N).max().shift(1); dn=d.close<d.low.rolling(N).min().shift(1)
        return first((up&lowv).astype(int)-(dn&lowv).astype(int))
    reg(f"squeeze n{n} q{q} N{N}",fn,EX)
# 2 trend pullback
for T,r,lo in itertools.product([672,2880],[6,14],[25,35]):
    def fn(s,d,T=T,r=r,lo=lo):
        e=d.close.ewm(span=T).mean(); up=(d.close>e)&(e>e.shift(96)); dn=(d.close<e)&(e<e.shift(96)); x=rsi(d.close,r)
        return first((up&(x<lo)).astype(int)-(dn&(x>100-lo)).astype(int))
    reg(f"pullback T{T} r{r} lo{lo}",fn,EX)
# 3 whale: avg trade size z with bar direction
for n,z,mode in itertools.product([4,16],[2,3],["follow","fade"]):
    def fn(s,d,n=n,z=z,mode=mode):
        ats=(d.quote_volume.rolling(n).sum()/d.trades.rolling(n).sum()); zz=(ats-ats.rolling(672).mean())/ats.rolling(672).std()
        dr=np.sign(d.close-d.close.shift(n))
        x=first(((zz>z)*dr).fillna(0).astype(int))
        return x if mode=="follow" else -x
    reg(f"whale n{n} z{z} {mode}",fn,EX)
# 4 cross-asset shock: other coin's shock, own lagging
for n,z,mode in itertools.product([1,4,16],[3,4],["follow","fade"]):
    def fn(s,d,n=n,z=z,mode=mode):
        o=D[OTH[s]]; zo=(np.log(o.close)-np.log(o.close.shift(n)))/(SG[OTH[s]]*np.sqrt(n))
        zs=(np.log(d.close)-np.log(d.close.shift(n)))/(SG[s]*np.sqrt(n))
        x=((zo>z)&(zs<z*0.6)).astype(int)-((zo<-z)&(zs>-z*0.6)).astype(int)
        return x if mode=="follow" else -x
    reg(f"xshock n{n} z{z} {mode}",fn,EX)
# 5 relative strength vs other coin (ratio z) follow/fade
for n,z,mode in itertools.product([16,96,384],[2,3],["follow","fade"]):
    def fn(s,d,n=n,z=z,mode=mode):
        r=np.log(d.close)-np.log(D[OTH[s]].close); x=(r-r.shift(n)); zz=x/(x.rolling(672*2).std())
        y=first((zz>z).astype(int)-(zz<-z).astype(int))
        return y if mode=="follow" else -y
    reg(f"relstr n{n} z{z} {mode}",fn,EX)
# 6 weekend range fade / weekday momentum
for N,mode,days in itertools.product([48,96],["follow","fade"],["wkend","wkday"]):
    def fn(s,d,N=N,mode=mode,days=days):
        dow=pd.Series(d.index.dayofweek,index=d.index); ok=(dow>=5) if days=="wkend" else (dow<5)
        x=first(((d.close>d.high.rolling(N).max().shift(1))&ok).astype(int)-((d.close<d.low.rolling(N).min().shift(1))&ok).astype(int))
        return x if mode=="follow" else -x
    reg(f"dowbrk N{N} {days} {mode}",fn,EX)
# 7 volume-confirmed breakout
for N,v in itertools.product([96,288,672],[2,4]):
    def fn(s,d,N=N,v=v):
        vs=d.volume/d.volume.rolling(672).mean()
        return first(((d.close>d.high.rolling(N).max().shift(1))&(vs>v)).astype(int)-((d.close<d.low.rolling(N).min().shift(1))&(vs>v)).astype(int))
    reg(f"volbrk N{N} v{v}",fn,EX)
# 8 funding extreme + momentum
for q,mode in itertools.product([0.0003,0.0005],["follow","fade"]):
    def fn(s,d,q=q,mode=mode):
        f=d.funding.replace(0,np.nan).ffill(); x=first((f>q).astype(int)-(f<-q/3).astype(int))
        return x if mode=="follow" else -x
    reg(f"fundlvl q{q} {mode}",fn,EX)
# 9 daily momentum at 00:00 by sign of last L bars, only if strong
for h,L,z in itertools.product([0,8,13,16],[96,288,672],[1.0,2.0]):
    def fn(s,d,h=h,L=L,z=z):
        mv=(np.log(d.close)-np.log(d.close.shift(L)))/(SG[s]*np.sqrt(L)); t=(d.index.hour==(h-1)%24)&(d.index.minute==45)
        return ((mv>z)&t).astype(int)-((mv<-z)&t).astype(int)
    reg(f"dmom h{h} L{L} z{z}",fn,[dict(maxhold=m) for m in [32,96,288]])
rows=[]
for name,(fn,exits) in fam.items():
    S={s:fn(s,D[s]).fillna(0).astype(int).values for s in D}
    for ex in exits:
        r=dict(name=name,ex=str(ex).replace("'","").replace("maxhold","mh"))
        for s,d in D.items():
            tr=bt(d,S[s],start=P0,**ex)
            r[s[:3]+"_n"]=len(tr); r[s[:3]+"_p1"]=round(tr[tr.exit<MID].ret.sum()*100,1); r[s[:3]+"_p2"]=round(tr[tr.exit>=MID].ret.sum()*100,1)
        rows.append(r)
df=pd.DataFrame(rows); c4=["BTC_p1","BTC_p2","ETH_p1","ETH_p2"]; df["min4"]=df[c4].min(axis=1); df["sum4"]=df[c4].sum(axis=1)
df.to_pickle("c10.pkl")
print(len(df),"configs, frac all4>0:",round((df.min4>0).mean(),3))
print(df[df[["BTC_n","ETH_n"]].min(axis=1)>=120].sort_values("min4",ascending=False).head(30).to_string(index=False))
df["fam"]=df.name.str.split().str[0]
print(df.groupby("fam").agg(n=("min4","size"),frac=("min4",lambda x:(x>0).mean()),best=("min4","max"),meansum=("sum4","mean")).round(2).sort_values("frac",ascending=False))
