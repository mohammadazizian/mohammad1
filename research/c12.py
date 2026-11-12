import itertools
from lib import *
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
def ld(s):
    d=pd.read_parquet(f"/home/user/mohammad1/data/{s}_5m.parquet")
    return d.resample("15min").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum","quote_volume":"sum","trades":"sum","taker_buy_base":"sum","funding":"sum"})
D={s:ld(s) for s in ["BTCUSDT","ETHUSDT"]}
MID=pd.Timestamp("2024-11-12",tz="UTC"); P0=pd.Timestamp("2022-11-12",tz="UTC")
SG={s:np.log(d.close).diff().rolling(672).std() for s,d in D.items()}
AT={s:atr(d,96) for s,d in D.items()}
fam={}
def reg(name,fn,exits): fam[name]=(fn,exits)
EX=[dict(maxhold=m,sl=s) for m in [16,48,96] for s in [0,4]]
first=lambda s: s.where(s!=s.shift(1),0)
def bars_since(d,h,m=0):
    t=(d.index.hour*60+d.index.minute-(h*60+m))%1440//15
    return pd.Series(t,index=d.index)
# 1 opening range breakout
for h0,K,W,mode in itertools.product([0,8,13],[4,8,16],[32,64],["follow","fade"]):
    def fn(s,d,h0=h0,K=K,W=W,mode=mode):
        b=bars_since(d,h0); day=(b==0).cumsum(); inr=b<K
        hi=d.high.where(inr).groupby(day).cummax().groupby(day).ffill(); lo=d.low.where(inr).groupby(day).cummin().groupby(day).ffill()
        act=(b>=K)&(b<K+W)
        x=((d.close>hi)&act).astype(int)-((d.close<lo)&act).astype(int)
        x=x.where(x.groupby(day).transform(lambda v:(v!=0).cumsum())==1,0); x=first(x)
        return x if mode=="follow" else -x
    reg(f"orb h{h0} K{K} W{W} {mode}",fn,EX)
# 2 intraday session momentum: return over [h-L,h] -> hold H
for h,L,z,mode in itertools.product([8,13,14,16,20,0],[8,16,32],[1.0,2.0],["follow"]):
    def fn(s,d,h=h,L=L,z=z):
        mv=(np.log(d.close)-np.log(d.close.shift(L)))/(SG[s]*np.sqrt(L)); t=(d.index.hour==(h-1)%24)&(d.index.minute==45)
        return ((mv>z)&t).astype(int)-((mv<-z)&t).astype(int)
    reg(f"sessmom h{h} L{L} z{z}",fn,[dict(maxhold=m) for m in [8,16,32,48]])
# 3 flow/price divergence
for n,fzT,pz,mode in itertools.product([4,16],[2,3],[0.5,1.0],["flow","antiflow"]):
    def fn(s,d,n=n,fzT=fzT,pz=pz,mode=mode):
        fl=(2*d.taker_buy_base-d.volume).rolling(n).sum(); fz=(fl-fl.rolling(672).mean())/fl.rolling(672).std()
        z=(np.log(d.close)-np.log(d.close.shift(n)))/(SG[s]*np.sqrt(n))
        x=first(((fz>fzT)&(z<pz)).astype(int)-((fz<-fzT)&(z>-pz)).astype(int))
        return x if mode=="flow" else -x
    reg(f"diverg n{n} f{fzT} p{pz} {mode}",fn,EX)
# 4 wick rejection with volume
for w,v,mode in itertools.product([1.0,1.5,2.5],[1,3],["rev","cont"]):
    def fn(s,d,w=w,v=v,mode=mode):
        a=AT[s]; vs=d.volume/d.volume.rolling(672).mean()
        lw=(np.minimum(d.open,d.close)-d.low)/a; uw=(d.high-np.maximum(d.open,d.close))/a
        x=((lw>w)&(vs>v)&(lw>2*uw)).astype(int)-((uw>w)&(vs>v)&(uw>2*lw)).astype(int)
        return x if mode=="rev" else -x
    reg(f"wick w{w} v{v} {mode}",fn,EX)
# 5 consecutive candles
for N,mode,vr in itertools.product([4,6,8],["follow","fade"],[0,1]):
    def fn(s,d,N=N,mode=mode,vr=vr):
        up=(d.close>d.open).rolling(N).sum()==N; dn=(d.close<d.open).rolling(N).sum()==N
        ok=(d.volume.rolling(N).mean()>1.5*d.volume.rolling(672).mean()) if vr else True
        x=first((up&ok).astype(int)-(dn&ok).astype(int))
        return x if mode=="follow" else -x
    reg(f"consec N{N} v{vr} {mode}",fn,EX)
# 6 trend-aligned / counter-trend shock
for n,z,T,mode in itertools.product([4,16],[3,4],[288,672],["aligned","counter"]):
    def fn(s,d,n=n,z=z,T=T,mode=mode):
        lc=np.log(d.close); zz=(lc-lc.shift(n))/(SG[s]*np.sqrt(n)); tr=np.sign(lc.shift(n)-lc.shift(n+T))
        sh=(zz>z).astype(int)-(zz<-z).astype(int)
        return sh.where(sh*tr>0,0).astype(int) if mode=="aligned" else sh.where(sh*tr<0,0).astype(int)
    reg(f"tshock n{n} z{z} T{T} {mode}",fn,EX)
# 7 distance from daily VWAP
for z,mode in itertools.product([1.5,2.5,3.5],["follow","fade"]):
    def fn(s,d,z=z,mode=mode):
        day=d.index.floor("1D"); tp=(d.high+d.low+d.close)/3
        vw=(tp*d.volume).groupby(day).cumsum()/d.volume.groupby(day).cumsum()
        x=(d.close-vw)/AT[s]; y=first((x>z).astype(int)-(x<-z).astype(int))
        return y if mode=="follow" else -y
    reg(f"vwap z{z} {mode}",fn,EX)
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
df.to_pickle("c12.pkl")
print(len(df),"configs, frac all4>0:",round((df.min4>0).mean(),3))
print(df[df[["BTC_n","ETH_n"]].min(axis=1)>=200].sort_values("min4",ascending=False).head(30).to_string(index=False))
df["fam"]=df.name.str.split().str[0]+" "+df.name.str.split().str[-1]
print(df.groupby("fam").agg(n=("min4","size"),frac=("min4",lambda x:(x>0).mean()),best=("min4","max"),meansum=("sum4","mean")).round(2).sort_values("frac",ascending=False).head(20))
