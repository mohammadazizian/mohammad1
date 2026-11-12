# Broad family search with in-sample (first 12m) / out-of-sample (last 12m) split on 15m
import itertools
from lib import *
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
D={s:load(s) for s in ["BTCUSDT","ETHUSDT"]}
MID=pd.Timestamp("2024-11-12",tz="UTC"); P0=pd.Timestamp("2022-11-12",tz="UTC")
def feats(d):
    f={}; c=d.close; lc=np.log(c); r=lc.diff()
    f["sg"]=r.rolling(96*7).std(); f["a"]=atr(d,96)
    f["vs"]=d.volume/d.volume.rolling(96*7).mean()
    f["dl"]=(2*d.taker_buy_base-d.volume)
    f["hr"]=pd.Series(d.index.hour,index=d.index); f["dow"]=pd.Series(d.index.dayofweek,index=d.index)
    return f
FE={s:feats(d) for s,d in D.items()}
fam={}
def reg(name,fn,exits): fam[name]=(fn,exits)
E_short=[dict(maxhold=m,sl=s) for m in [4,16,48] for s in [0,3]]
E_long=[dict(maxhold=m,sl=s) for m in [48,96,288] for s in [0,5]]
E_tp=[dict(maxhold=96,sl=s,tp=t) for s in [2,4] for t in [1,2,4]]
# 1 vol shock (both directions) -> long / short / follow / fade
for n,z,mode in itertools.product([1,4,16],[3,4,6],["long","short","follow","fade"]):
    def fn(d,f,n=n,z=z,mode=mode):
        x=(np.log(d.close)-np.log(d.close.shift(n)))/(f["sg"]*np.sqrt(n))
        up=(x>z).astype(int); dn=(x<-z).astype(int)
        return {"long":up+dn,"short":-(up+dn),"follow":up-dn,"fade":dn-up}[mode]
    reg(f"shock n{n} z{z} {mode}",fn,E_short+E_long)
# 2 delta absorption: strong taker imbalance but small price move -> fade/follow imbalance
for n,q,mode in itertools.product([4,16,96],[2,3],["follow","fade"]):
    def fn(d,f,n=n,q=q,mode=mode):
        x=f["dl"].rolling(n).sum(); z=(x-x.rolling(96*7).mean())/x.rolling(96*7).std()
        s=(z>q).astype(int)-(z<-q).astype(int)
        return s if mode=="follow" else -s
    reg(f"delta n{n} q{q} {mode}",fn,E_short+E_long)
# 3 funding contrarian / follow
for q,mode in itertools.product([1,2,3],["follow","fade"]):
    def fn(d,f,q=q,mode=mode):
        x=d.funding.rolling(96).sum(); z=(x-x.rolling(96*30).mean())/x.rolling(96*30).std()
        s=((z>q).astype(int)-(z<-q).astype(int))*(d.funding!=0)
        return s if mode=="follow" else -s
    reg(f"fund q{q} {mode}",fn,E_long)
# 4 session range breakout: asia range (0-8 UTC) breakout during 8-16 ; follow/fade
for h0,h1,mode in itertools.product([(0,7),(0,12),(20,7)],[4,8],["follow","fade"]):
    def fn(d,f,h0=h0,h1=h1,mode=mode):
        hr=f["hr"]; inr=(hr>=h0[0])&(hr<h0[1]) if h0[0]<h0[1] else (hr>=h0[0])|(hr<h0[1])
        g=(inr&~inr.shift(1,fill_value=False)).cumsum()
        hi=d.high.where(inr).groupby(g).cummax().ffill(); lo=d.low.where(inr).groupby(g).cummin().ffill()
        act=(~inr)&(((hr-h0[1])%24)<h1)
        s=((d.close>hi)&act).astype(int)-((d.close<lo)&act).astype(int)
        s=s.where(s!=s.shift(1),0)
        return s if mode=="follow" else -s
    reg(f"sess {h0} {h1} {mode}",fn,E_short+E_long+E_tp)
# 5 weekend/CME gap: at sunday 22:00 UTC fade move since friday 21:00
for thr,mode in itertools.product([0,1,2],["follow","fade"]):
    def fn(d,f,thr=thr,mode=mode):
        fri=d.close.where((f["dow"]==4)&(f["hr"]==20)&(d.index.minute==45)).ffill()
        mv=(np.log(d.close)-np.log(fri))/(f["sg"]*np.sqrt(96*2))
        t=(f["dow"]==6)&(f["hr"]==21)&(d.index.minute==45)
        s=((mv>thr)&t).astype(int)-((mv<-thr)&t).astype(int)
        return s if mode=="follow" else -s
    reg(f"cme thr{thr} {mode}",fn,E_long)
# 6 bollinger z of close vs ema, fade/follow, with vol regime
for n,z,mode,reg_ in itertools.product([20,96,384],[2,3],["follow","fade"],["any","lowvol","highvol"]):
    def fn(d,f,n=n,z=z,mode=mode,reg_=reg_):
        m=d.close.rolling(n).mean(); sd=d.close.rolling(n).std(); x=(d.close-m)/sd
        rv=np.log(d.close).diff().rolling(96).std()/f["sg"]
        ok={"any":True,"lowvol":rv<0.8,"highvol":rv>1.2}[reg_]
        s=((x>z)&ok).astype(int)-((x<-z)&ok).astype(int)
        s=s.where(s!=s.shift(1),0)
        return s if mode=="follow" else -s
    reg(f"boll n{n} z{z} {mode} {reg_}",fn,E_short+E_long+E_tp)
# 7 time-of-day fixed entries long/short
for h,dirn in itertools.product(range(0,24,1),[1,-1]):
    def fn(d,f,h=h,dirn=dirn):
        return ((f["hr"]==h)&(d.index.minute==45)).astype(int)*dirn
    reg(f"tod h{h} dir{dirn}",fn,[dict(maxhold=m) for m in [4,8,16]])
for N,mode in itertools.product([96,288,672,1344,2880],["follow","fade"]):
    def fn(d,f,N=N,mode=mode):
        ph=d.high.rolling(N).max().shift(1); pl=d.low.rolling(N).min().shift(1)
        s=(d.close>ph).astype(int)-(d.close<pl).astype(int)
        return s if mode=="follow" else -s
    reg(f"donch N{N} {mode}",fn,[dict(trail=t) for t in [6,10,15]]+E_long)
for a,b in [(96,384),(192,768),(384,1536),(672,2880)]:
    def fn(d,f,a=a,b=b):
        x=(d.close.ewm(span=a).mean()>d.close.ewm(span=b).mean()).astype(int)*2-1
        return x
    reg(f"emax {a}/{b}",fn,[dict(opp=True)])
rows=[]
for name,(fn,exits) in fam.items():
    S={s:fn(D[s],FE[s]).fillna(0).astype(int).values for s in D}
    for ex in exits:
        r=dict(name=name,ex=str(ex).replace("'","").replace("maxhold","mh"))
        ok=True
        for s,d in D.items():
            tr=bt(d,S[s],start=P0,**ex)
            a=tr[tr.exit<MID]; b=tr[tr.exit>=MID]
            m,cnt=monthly(tr[tr.entry>=MID])
            r[s[:3]+"_n"]=len(tr); r[s[:3]+"_is"]=round(a.ret.sum()*100,1); r[s[:3]+"_oos"]=round(b.ret.sum()*100,1)
            r[s[:3]+"_pos"]=int((m>0).sum()); r[s[:3]+"_minc"]=int(cnt.min())
            r[s[:3]+"_avg"]=round(tr.ret.mean()*1e4,1) if len(tr) else 0
        rows.append(r)
df=pd.DataFrame(rows)
df["IS"]=df.BTC_is+df.ETH_is; df["OOS"]=df.BTC_oos+df.ETH_oos
df["minIS"]=df[["BTC_is","ETH_is"]].min(axis=1)
df.to_pickle("c5b.pkl")
print(len(df),"configs; frac IS>0:",(df.IS>0).mean().round(3),"frac OOS>0:",(df.OOS>0).mean().round(3))
c4=["BTC_is","BTC_oos","ETH_is","ETH_oos"]
df["min4"]=df[c4].min(axis=1); df["sum4"]=df[c4].sum(axis=1)
print("P1=2022-24 (is cols), P2=2024-26 (oos cols)")
print(df[df[["BTC_n","ETH_n"]].min(axis=1)>=100].sort_values("min4",ascending=False).head(40).drop(columns=["IS","OOS","minIS"]).to_string(index=False))
print("frac all4>0:",(df.min4>0).mean())
