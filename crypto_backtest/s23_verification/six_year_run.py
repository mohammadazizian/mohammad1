exec(open('oos_test.py').read().split("print('=== 1.")[0])
C,E=T('2020-11-12'),T('2026-11-12'); ALL=S2X_STREAMS+S3X_STREAMS
print('=== full six years 2020-11-12 -> 2026-11-12, BTC+ETH (S2x, S3x) + SOL (S3x), leverage cap 3x, compounding')
out={}
for risk,lock,cost in [(0.005,0.07,None),(0.005,0.07,0.0014),(0.005,0.07,0.0020),(0.01,0.07,None),(0.01,0.10,None),(0.01,0.10,0.0014),(0.01,0.10,0.0020),(0.0025,0.07,None)]:
    kw=dict(risk=risk,month_loss=lock); 
    if cost: kw['cost']=cost
    tr,mr=go(f'risk {risk*100:g}% lock -{lock*100:g}% cost {(cost or 0.001)*100:.2f}%',ALL,SL,TP,C,E,**kw)
    m=mr*100; out[(risk,lock,cost)]=m
    a=m[:'2022-11-30']; b=m['2022-12-01':]
    print(f"      median month {m.median():+.1f}%  months>=8%: {(m>=8).sum()}/{len(m)}  months+: {100*(m>0).mean():.0f}%  | 2020-22 part: median {a.median():+.1f}% >=8%: {(a>=8).sum()}/{len(a)} months+ {(a>0).sum()}/{len(a)} | 2022-26 part: median {b.median():+.1f}% >=8%: {(b>=8).sum()}/{len(b)} months+ {(b>0).sum()}/{len(b)}")
for key in [(0.005,0.07,None),(0.01,0.10,None)]:
    m=out[key]; print(f'\nmonthly % risk {key[0]*100:g}%:'); 
    t=pd.DataFrame({'y':m.index.year,'mo':m.index.month,'v':m.values}).pivot(index='mo',columns='y',values='v').round(1); print(t.to_string(na_rep=''))
tr,eq=run(ALL,SL,TP,start=C,end=E,lev_cap=3.0,compound=True,rmult=RMULT,risk=0.005,month_loss=0.07,vol_max=0.8,trend_sleeves=("Sx","Fx"))
print('\nexit kinds:',tr.kind.value_counts().to_dict(),' trades/month',round(len(tr)/72,1),' by stream pnl share:',(tr.groupby('stream').pnl.sum()/tr.pnl.sum()).round(2).to_dict())
ls=max(len(list(g)) for k,g in itertools.groupby(tr.sort_values('exit').pnl<0) if k); print('longest losing streak (trades):',ls)
