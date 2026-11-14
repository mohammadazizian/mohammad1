exec(open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'time_of_day.py')).read().split("print('mean hourly return")[0])
LO=np.log(O); sig=LO.diff().rolling(168).std(); COST=0.0010
rows=[]
for h,L,k,W in itertools.product([18,20,22],[12,24],[4,8,12],[90,180,365]):
    m=hr==h
    mv=((LO-LO.shift(L))/(sig*np.sqrt(L)))[m]; ret=(LO.shift(-k)-LO)[m]; fund=F.rolling(k).sum().shift(-k)[m]
    d=np.sign(mv).where(mv.abs()>0.5)
    gross=(d*ret).mean(axis=1)                         # daily 'follow' result, average of coins
    reg=np.sign(gross.fillna(0).rolling(W).sum().shift(1))   # regime known before today's trade (trades are closed within 12h)
    net=(d.mul(reg,axis=0)*ret-COST-d.mul(reg,axis=0)*fund)
    net=net[reg.notna()&(reg!=0)]
    pm=net.mean(axis=1); pm=pm['2023-01-01':]
    mo=pm.groupby(pm.index.to_period('M')).sum()*100; yrs=mo.groupby(mo.index.year).sum().round(0).astype(int).tolist()
    st=net['2023-01-01':].stack()
    rows.append(dict(h=h,L=L,k=k,W=W,avg_bp=round(st.mean()*1e4,1),t=round(st.mean()/st.std()*np.sqrt(len(st)),1),months_pos=round(100*(mo>0).mean()),tot=round(mo.sum()),worst=round(mo.min(),1),yrs=yrs,coins_pos=int((net['2023-01-01':].mean()>0).sum()),flips=int((reg.dropna().diff()!=0).sum())))
R=pd.DataFrame(rows); pd.set_option('display.width',220); print(R.to_string()); print('variants positive:',(R.avg_bp>0).sum(),'of',len(R),' median avg bp',R.avg_bp.median(),' median months+',R.months_pos.median())
