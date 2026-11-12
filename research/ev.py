from lib import *
pd.set_option("display.width",250); pd.set_option("display.max_rows",500)
D={s:load(s,"5min") for s in ["BTCUSDT","ETHUSDT"]}
D={s:d[d.index>=START-pd.Timedelta(days=30)] for s,d in D.items()}
mid=START+(END-START)/2
rows=[]
for s,d in D.items():
    lc=np.log(d.close); sig=lc.diff().rolling(288*7).std()
    vs=d.volume/d.volume.rolling(288*7).mean()
    delta=(2*d.taker_buy_base-d.volume)/d.volume
    for n in [1,3,12]:
        z=(lc-lc.shift(n))/(sig*np.sqrt(n))
        for zt in [3,5,8]:
            for vt in [0,3]:
                for side,m in [("dn",(z<-zt)),("up",(z>zt))]:
                    m=m&(vs.rolling(n).mean()>vt)&(d.index>=START)
                    # de-dup: first event in 12 bars
                    m=m&(~m.shift(1).rolling(12).max().fillna(0).astype(bool))
                    for h in [3,12,48,288]:
                        f=(np.log(d.open.shift(-h-1))-np.log(d.open.shift(-1)))[m]*1e4
                        rows.append([s[:3],n,zt,vt,side,h,len(f),f.mean(),f.median(),f[f.index<mid].mean(),f[f.index>=mid].mean(),f.mean()/f.std()*np.sqrt(len(f)) if len(f)>3 else 0])
df=pd.DataFrame(rows,columns="s n z v side h cnt mean med h1 h2 t".split()).round(1)
df=df[df.cnt>=30]
p=df.pivot_table(index=["n","z","v","side","h"],columns="s",values=["cnt","mean","h1","h2","t"])
p["mt"]=p["t"].abs().min(axis=1)*np.sign(p["t"]["BTC"])*(np.sign(p["t"]["BTC"])==np.sign(p["t"]["ETH"]))
print(p.sort_values("mt").head(15).to_string()); print(p.sort_values("mt").tail(15).to_string())
# lead-lag
b=np.log(D["BTCUSDT"].close).diff(); e=np.log(D["ETHUSDT"].close).diff()
print("corr btc_t->eth_t+1",b.corr(e.shift(-1)),"eth->btc",e.corr(b.shift(-1)),"auto btc",b.corr(b.shift(-1)),"auto eth",e.corr(e.shift(-1)))
