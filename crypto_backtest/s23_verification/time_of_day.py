import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import numpy as np, pandas as pd, itertools, warnings
import strategy_v2 as V
warnings.filterwarnings('ignore')
COINS=[s[:-4] for s in V.TOP10]
O=pd.DataFrame({k:V.load(k+'USDT')[0].open for k in COINS}).loc['2022-01-01':'2026-10-31'].ffill()
F=pd.DataFrame({k:V.load(k+'USDT')[1].pipe(lambda fr: fr.groupby(fr.index.floor('1h')).sum()) for k in COINS}).reindex(O.index).fillna(0)
R=np.log(O).diff().shift(-1)            # return of the hour starting at index time
yr=O.index.year; hr=O.index.hour; dow=O.index.dayofweek
print('mean hourly return by UTC hour, bps, average of 10 coins, by year')
T=pd.DataFrame({y:(R[yr==y].groupby(hr[yr==y]).mean().mean(axis=1)*1e4) for y in range(2022,2027)}).round(1)
T['same_sign_years']=(np.sign(T[[2022,2023,2024,2025,2026]]).sum(axis=1)).abs().astype(int)
pool=R.mean(axis=1); T['t_all']=(pool.groupby(hr).mean()/pool.groupby(hr).std()*np.sqrt(pool.groupby(hr).count())).round(1)
print(T.to_string())
print('\nBTC only'); Tb=pd.DataFrame({y:(R.BTC[yr==y].groupby(hr[yr==y]).mean()*1e4) for y in range(2022,2027)}).round(1); print(Tb.T.to_string())
print('\nday of week (0=Mon) mean daily return bps, avg 10 coins, by year')
D=pd.DataFrame({y:(R[yr==y].groupby(dow[yr==y]).sum().mean(axis=1)/ (R[yr==y].groupby(dow[yr==y]).count().mean(axis=1)/24)*1e4) for y in range(2022,2027)}).round(0); print(D.T.to_string())
COST=0.0010
tr=slice('2022-01-01','2024-12-31'); va=slice('2025-01-01','2026-10-31')
def stats(x):
    x=x.dropna(); 
    return (x.mean()*1e4, x.mean()/x.std()*np.sqrt(len(x)) if len(x)>5 and x.std()>0 else 0, len(x))
# (a) unconditional: enter at hour h, hold k hours, long or short
rows=[]
LO=np.log(O)
for h,k in itertools.product(range(24),[1,2,4,8,12,24]):
    m=hr==h
    ret=(LO.shift(-k)-LO)[m]; fund=F.rolling(k).sum().shift(-k)[m]   # funding stamps inside (entry, entry+k]
    for sgn in (1,-1):
        net=sgn*ret-COST-sgn*fund
        a=stats(net[tr].stack()); b=stats(net[va].stack())
        pm=net.mean(axis=1); mo=pm.groupby(pm.index.to_period('M')).sum()
        rows.append(dict(kind='uncond',h=h,k=k,side=sgn,avg_tr=a[0],t_tr=a[1],avg_va=b[0],t_va=b[1],months_pos=100*(mo>0).mean(),coins_tr=(net[tr].mean()>0).sum(),coins_va=(net[va].mean()>0).sum()))
# (b) conditional: at hour h, look at past L-hour move; follow or fade if |move| > 0.5 sigma; hold k
sig=np.log(O).diff().rolling(168).std()
for h,L,k in itertools.product(range(24),[4,8,12,24],[4,8,12,24]):
    m=hr==h
    mv=((LO-LO.shift(L))/(sig*np.sqrt(L)))[m]; ret=(LO.shift(-k)-LO)[m]; fund=F.rolling(k).sum().shift(-k)[m]
    d=np.sign(mv).where(mv.abs()>0.5)
    for sgn,nm in ((1,'follow'),(-1,'fade')):
        net=(sgn*d*ret-COST-sgn*d*fund)
        a=stats(net[tr].stack()); b=stats(net[va].stack())
        pm=net.mean(axis=1); mo=pm.groupby(pm.index.to_period('M')).sum()
        rows.append(dict(kind=nm,h=h,k=k,L=L,side=sgn,avg_tr=a[0],t_tr=a[1],avg_va=b[0],t_va=b[1],months_pos=100*(mo>0).mean(),coins_tr=(net[tr].mean()>0).sum(),coins_va=(net[va].mean()>0).sum()))
Rr=pd.DataFrame(rows); pd.set_option('display.width',220)
print('\nconfigs:',len(Rr),' positive after costs in train:',(Rr.avg_tr>0).sum(),' of those positive in validation:',((Rr.avg_tr>0)&(Rr.avg_va>0)).sum())
print('train t>2:',(Rr.t_tr>2).sum(),' of those valid avg>0:',((Rr.t_tr>2)&(Rr.avg_va>0)).sum(),' valid t>2:',((Rr.t_tr>2)&(Rr.t_va>2)).sum())
print('corr(train t, valid t):',Rr.t_tr.corr(Rr.t_va).round(2), ' by kind:',Rr.groupby('kind').apply(lambda g:g.t_tr.corr(g.t_va)).round(2).to_dict())
print(Rr.sort_values('t_tr',ascending=False).head(20).round(1).to_string())
print('\nbest by min(train t, valid t):'); Rr['mn']=Rr[['t_tr','t_va']].min(axis=1); print(Rr.sort_values('mn',ascending=False).head(15).round(1).to_string())
