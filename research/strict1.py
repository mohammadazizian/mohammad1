import sys, itertools; sys.path.insert(0,"/home/user/mohammad1")
from mm import *
import mm
pd.set_option("display.width",250)
COINS2=["BTCUSDT","ETHUSDT"]; COINS3=["BTCUSDT","ETHUSDT","SOLUSDT"]
RAW={}
def raw(sym):
    if sym not in RAW:
        d=data(sym)["d"]; lc=np.log(d.close); sg=lc.diff().rolling(672).std()
        z=(lc-lc.shift(4))/(sg*2)
        flow=(2*d.taker_buy_base-d.volume).rolling(16).sum(); fz=(flow-flow.rolling(672).mean())/flow.rolling(672).std()
        ats=d.quote_volume.rolling(4).sum()/d.trades.rolling(4).sum(); az=(ats-ats.rolling(672).mean())/ats.rolling(672).std()
        pd4=np.sign(d.close-d.close.shift(4))
        vs=d.volume.rolling(4).sum()/(d.volume.rolling(672).mean()*4)
        RAW[sym]=dict(z=z,fz=fz,az=az,pd4=pd4,vs=vs,tr7=np.sign(lc-lc.shift(672)),tr30=np.sign(lc-lc.shift(2880)),volrank=pd.Series(data(sym)["volrank"],index=d.index))
    return RAW[sym]
def build(sym,p):
    r=raw(sym); ok=(r["volrank"]<=p.get("vol",1.0))
    S=((r["z"]>p.get("sz",4)).astype(int)-(r["z"]<-p.get("sz",4)).astype(int))
    F=((r["fz"]>p.get("fzt",3)).astype(int)-(r["fz"]<-p.get("fzt",3)).astype(int))
    if p.get("conf",0)>0:                      # confluence: shock needs flow in the same direction and vice versa
        S=S.where(np.sign(r["fz"])*S>0,0).where(r["fz"].abs()>p["conf"],0)
        F=F.where(np.sign(r["z"])*F>0,0).where(r["z"].abs()>p["conf"],0)
    W=((r["az"]>p.get("wz",2))*r["pd4"]).fillna(0).astype(int)
    if p.get("wshock",0)>0: W=W.where(r["z"].abs()>p["wshock"],0)       # whale signal needs a real price move too
    if p.get("wvol",0)>0: W=W.where(r["vs"]>p["wvol"],0)
    W=W.where(W!=W.shift(1),0)
    for nm,x in [("S",S),("F",F),("W",W)]:
        x=x.where(ok,0)
        t=p.get("tr2" if nm!="W" else "tr3",None)
        if t: x=x.where(x==r[t],0)
        mm._cache[sym][nm+"x"]=x.fillna(0).astype(np.int64).values
mm.HOLD.update({"Sx":48,"Fx":48,"Wx":96})
SLx={(c,s+"x"):SL[(c,s)] for (c,s) in SL}; TPx={(c,s+"x"):TP[(c,s)] for (c,s) in TP}
STREAMS=[(c,"Sx") for c in COINS2]+[(c,"Fx") for c in COINS2]+[(c,"Wx") for c in COINS3]
def test(tag,p,sl=None,tp=None):
    for c in COINS3: build(c,p)
    tr,_=run(STREAMS,sl or SLx,tp or TPx,risk=0.01,compound=False)
    R=tr.pnl/0.01; s2=~tr.stream.str.endswith("Wx"); pre=tr.exit.dt.year<2026
    def f(m): 
        r=R[m]; return f"n {len(r):4d} win {(r>0).mean()*100:4.1f}% avgR {r.mean():+.3f}" if len(r) else "n 0"
    print(f"{tag:40s} S2[{f(s2)} | pre {R[s2&pre].sum():5.0f} 26 {R[s2&~pre].sum():4.0f}]  S3[{f(~s2)} | pre {R[~s2&pre].sum():5.0f} 26 {R[~s2&~pre].sum():4.0f}]",flush=True)
B0=dict(vol=0.8)
test("base (vol<=0.8)",B0)
test("+ trend30 S2",dict(B0,tr2="tr30"))
test("+ trend7 S2",dict(B0,tr2="tr7"))
test("+ trend7 S3",dict(B0,tr3="tr7"))
test("+ trend30 S3",dict(B0,tr3="tr30"))
for c in [1,2,3]: test(f"+ confluence {c}",dict(B0,conf=c))
for sz,fzt in [(5,3.5),(6,4)]: test(f"+ thresholds shock{sz} flow{fzt}",dict(B0,sz=sz,fzt=fzt))
for wz in [2.5,3,4]: test(f"+ whale z {wz}",dict(B0,wz=wz))
for ws in [1,2,3]: test(f"+ whale needs shock {ws}",dict(B0,wshock=ws))
for wv in [1.5,2.5]: test(f"+ whale needs volume x{wv}",dict(B0,wvol=wv))
for v in [0.6,0.5]: test(f"vol<= {v}",dict(vol=v))
